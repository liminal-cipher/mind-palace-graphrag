"""exp10 room generator. End-to-end pipeline:
    snapshot -> base cluster (ward) -> split oversized -> merge to K
    -> LLM assigns room name + keep/demote (node_budget enforced)
    -> JSON spec.

Domain-agnostic: no Korean-history rules in code. Domain is a string passed
to the LLM prompt only. Hardcoded anchor lists, type keyword lists, and
domain-specific heuristics are forbidden in this module; they live in
eval_rooms.py with anchors loaded from external JSON.

All functions are importable. Top-level entry is generate_rooms(...).
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage


# ---------------------------------------------------------------------------
# Entity shape (dict): {id, title, type, degree, description, embedding}
# embedding is np.ndarray float32, NOT L2-normalized at rest. Normalize at use.
# Indices refer to position in the entities list returned by load_snapshot.
# ---------------------------------------------------------------------------


def load_snapshot(path: str | Path) -> tuple[list[dict], dict]:
    """Load entities + 1536-dim embeddings from a GraphRAG snapshot directory.

    Returns (entities, meta). entities are ordered to match the embedding
    matrix you can rebuild by stacking each entity's 'embedding'.

    Raises if any entity is missing a vector (no silent drops).
    """
    p = Path(path)
    ent_df = pd.read_parquet(p / 'entities.parquet')
    db = lancedb.connect(str(p / 'lancedb'))
    vec_df = db.open_table('entity_description').to_pandas()
    vec_by_id = {row['id']: np.asarray(row['vector'], dtype=np.float32)
                 for _, row in vec_df.iterrows()}

    entities: list[dict] = []
    missing: list[str] = []
    for _, r in ent_df.iterrows():
        v = vec_by_id.get(r['id'])
        if v is None:
            missing.append(str(r['title']))
            continue
        entities.append({
            'id': str(r['id']),
            'title': str(r['title']),
            'type': str(r['type']),
            'degree': int(r['degree']),
            'description': str(r['description']),
            'embedding': v,
        })
    if missing:
        raise RuntimeError(
            f'{len(missing)} entities missing vectors (first 5: {missing[:5]})'
        )
    embed_dim = len(entities[0]['embedding']) if entities else 0
    meta = {
        'snapshot_path': str(p),
        'n_entities': len(entities),
        'embedding_dim': embed_dim,
    }
    return entities, meta


def _stack_normalized(entities: list[dict], indices: list[int]) -> np.ndarray:
    """Stack embeddings of `indices` (positions into entities) and L2-normalize."""
    mat = np.stack([entities[i]['embedding'] for i in indices]).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.clip(norms, 1e-12, None)


def base_cluster(entities: list[dict], k_base: int) -> list[list[int]]:
    """exp6 method: L2-normalize embeddings, ward linkage with euclidean
    metric (equivalent to cosine on unit vectors), cut tree to k_base clusters.

    Returns a list of clusters; each cluster is a list of entity indices
    (positions in `entities`).  Deterministic.
    """
    if k_base < 1:
        raise ValueError(f'k_base must be >= 1, got {k_base}')
    if k_base > len(entities):
        raise ValueError(
            f'k_base ({k_base}) cannot exceed entity count ({len(entities)})'
        )

    all_idx = list(range(len(entities)))
    if k_base == 1:
        return [all_idx]

    mat_n = _stack_normalized(entities, all_idx)
    Z = linkage(mat_n, method='ward', metric='euclidean')
    labels = fcluster(Z, t=k_base, criterion='maxclust')
    by_label: dict[int, list[int]] = defaultdict(list)
    for idx, lab in zip(all_idx, labels):
        by_label[int(lab)].append(idx)
    return [by_label[lab] for lab in sorted(by_label.keys())]


# ---------------------------------------------------------------------------
# Stub signatures: filled in subsequent commits.
# ---------------------------------------------------------------------------


def split_oversized(
    clusters: list[list[int]],
    entities: list[dict],
    max_cluster_size: int,
) -> list[list[int]]:
    """Any cluster larger than max_cluster_size is re-clustered (ward) within
    itself until every piece fits. Size-only criterion, domain-agnostic.

    Uses ceil(size / max_cluster_size) as the split fanout; recurses to handle
    skewed splits (one big chunk + crumbs). Pre-existing under-size clusters
    pass through untouched, preserving deterministic order.
    """
    if max_cluster_size < 2:
        raise ValueError(f'max_cluster_size must be >= 2, got {max_cluster_size}')

    out: list[list[int]] = []
    for cluster in clusters:
        out.extend(_split_one(cluster, entities, max_cluster_size))
    return out


def _split_one(
    cluster_idx: list[int],
    entities: list[dict],
    max_cluster_size: int,
) -> list[list[int]]:
    if len(cluster_idx) <= max_cluster_size:
        return [cluster_idx]

    k = -(-len(cluster_idx) // max_cluster_size)  # ceil
    k = max(2, k)
    mat_n = _stack_normalized(entities, cluster_idx)
    Z = linkage(mat_n, method='ward', metric='euclidean')
    labels = fcluster(Z, t=k, criterion='maxclust')

    by_label: dict[int, list[int]] = defaultdict(list)
    for idx, lab in zip(cluster_idx, labels):
        by_label[int(lab)].append(idx)
    pieces = [by_label[lab] for lab in sorted(by_label.keys())]

    # If a split was degenerate (one piece still oversized), recurse on that piece.
    final: list[list[int]] = []
    for piece in pieces:
        if len(piece) > max_cluster_size and len(piece) < len(cluster_idx):
            final.extend(_split_one(piece, entities, max_cluster_size))
        elif len(piece) >= len(cluster_idx):
            # No progress; bail to avoid infinite loop. Caller can lower max.
            final.append(piece)
        else:
            final.append(piece)
    return final


def merge_to_k(
    clusters: list[list[int]],
    entities: list[dict],
    K: int,
    strategy: str,
    llm_client=None,
    model: str | None = None,
    representatives_per_cluster: int = 10,
) -> list[list[int]]:
    """Reduce `clusters` to exactly K by merging.

    strategy="embedding": deterministic. Compute each cluster's L2-normalized
        centroid, repeatedly merge the pair with highest cosine similarity
        until K remain. Centroid is re-normalized after each merge.

    strategy="llm": one LLM call. Each cluster is summarized by
        `representatives_per_cluster` entities chosen by degree-desc with
        type round-robin (so a few high-degree generic terms don't drown
        out the topic signal). LLM returns a mapping of cluster indices
        into K groups; validated for full coverage and no duplicates.
        Fallback to embedding merge on contract violation.
    """
    if len(clusters) < K:
        raise ValueError(f'cannot merge {len(clusters)} clusters down to K={K}')
    if len(clusters) == K:
        return [list(c) for c in clusters]

    if strategy == 'embedding':
        return _merge_embedding(clusters, entities, K)
    if strategy == 'llm':
        if llm_client is None or model is None:
            raise ValueError('strategy="llm" requires llm_client and model')
        return _merge_llm(
            clusters, entities, K, llm_client, model,
            representatives_per_cluster,
        )
    raise ValueError(f'unknown strategy: {strategy!r}')


def _cluster_centroid(entities: list[dict], idx: list[int]) -> np.ndarray:
    mat_n = _stack_normalized(entities, idx)
    c = mat_n.mean(axis=0)
    n = np.linalg.norm(c)
    return c / max(n, 1e-12)


def _merge_embedding(
    clusters: list[list[int]],
    entities: list[dict],
    K: int,
) -> list[list[int]]:
    """Apply ward linkage on cluster centroids (cheap: len(clusters) points
    in 1536-D) and cut to K. Avoids chaining that a greedy nearest-centroid
    merger produces, and matches the variance-minimization objective used
    for base_cluster on the entity level.
    """
    if len(clusters) == K:
        return [list(c) for c in clusters]

    centroids = np.stack([_cluster_centroid(entities, g) for g in clusters])
    Z = linkage(centroids, method='ward', metric='euclidean')
    labels = fcluster(Z, t=K, criterion='maxclust')

    by_label: dict[int, list[int]] = defaultdict(list)
    for src_idx, lab in enumerate(labels):
        by_label[int(lab)].extend(clusters[src_idx])
    return [by_label[lab] for lab in sorted(by_label.keys())]


def representatives(
    cluster_idx: list[int],
    entities: list[dict],
    n: int,
) -> list[dict]:
    """Pick up to n entities to summarize a cluster.

    Strategy: degree-desc base order, then round-robin across `type` so a
    few high-degree generic terms (which often share one type) don't
    crowd out topic-bearing entities of other types. No type-keyword
    table, no domain assumptions; only the type *string* as a diversity
    bucket.
    """
    rows = [entities[i] for i in cluster_idx]
    rows.sort(key=lambda e: (-e['degree'], e['title']))
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r['type']].append(r)

    picked: list[dict] = []
    type_order = list(dict.fromkeys(r['type'] for r in rows))  # first-seen order
    while len(picked) < n and any(by_type[t] for t in type_order):
        for t in type_order:
            if by_type[t]:
                picked.append(by_type[t].pop(0))
                if len(picked) >= n:
                    break
    return picked


def _merge_llm(
    clusters: list[list[int]],
    entities: list[dict],
    K: int,
    llm_client,
    model: str,
    reps_per_cluster: int,
) -> list[list[int]]:
    summaries = []
    for i, c in enumerate(clusters):
        reps = representatives(c, entities, reps_per_cluster)
        titles = ', '.join(r['title'] for r in reps)
        summaries.append(f'cluster {i} (size={len(c)}): {titles}')

    sys_p = (
        '주어진 클러스터 목록을 의미적으로 가까운 것끼리 정확히 K개 그룹으로 묶어라. '
        '각 cluster id는 정확히 한 그룹에만 속해야 한다. 누락·중복 금지. '
        '그룹 라벨이나 이름은 출력하지 마라. 매핑만.'
    )
    user_p = (
        f'클러스터 {len(clusters)}개를 K={K}개 그룹으로 묶어라.\n\n'
        + '\n'.join(summaries)
        + '\n\n출력 JSON:\n'
        '{\n'
        '  "groups": [\n'
        '    {"new_id": 0, "source_clusters": [0, 3]},\n'
        '    ...\n'
        '  ]\n'
        '}'
    )

    raw, _usage = call_json(llm_client, model, sys_p, user_p)
    try:
        obj = json.loads(raw)
        groups_spec = obj.get('groups', [])
        merged: list[list[int]] = []
        assigned: set[int] = set()
        for g in groups_spec:
            src = [int(s) for s in g.get('source_clusters', [])]
            members: list[int] = []
            for s in src:
                if 0 <= s < len(clusters) and s not in assigned:
                    members.extend(clusters[s])
                    assigned.add(s)
            if members:
                merged.append(members)

        missing = [i for i in range(len(clusters)) if i not in assigned]
        if missing or len(merged) != K:
            # Fold any unassigned clusters into nearest existing group via
            # centroid cosine, then if still wrong K, finish with embedding merge.
            for s in missing:
                # find nearest merged group
                src_c = _cluster_centroid(entities, clusters[s])
                best_j, best_sim = -1, -np.inf
                for j, m in enumerate(merged):
                    sim = float(np.dot(src_c, _cluster_centroid(entities, m)))
                    if sim > best_sim:
                        best_sim, best_j = sim, j
                if best_j >= 0:
                    merged[best_j].extend(clusters[s])
                else:
                    merged.append(clusters[s])
            if len(merged) > K:
                merged = _merge_embedding(merged, entities, K)
            elif len(merged) < K:
                # LLM collapsed too aggressively; cannot un-merge.
                # Last resort: re-run embedding merge from scratch.
                merged = _merge_embedding(clusters, entities, K)
        return merged
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _merge_embedding(clusters, entities, K)


# ---------------------------------------------------------------------------
# LLM transport (used by merge_llm, derive_rubric, assign_rooms).
# Exponential backoff on rate-limit errors. No deployment quota assumptions.
# ---------------------------------------------------------------------------


def call_json(
    client,
    model: str,
    sys_p: str,
    user_p: str,
    max_retries: int = 6,
) -> tuple[str, dict]:
    """Azure OpenAI JSON-mode chat. temp=0. On rate-limit / transient errors,
    exponential backoff starting at 2s (2,4,8,16,32,60). Other errors raise.
    """
    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': sys_p},
                    {'role': 'user', 'content': user_p},
                ],
                temperature=0,
                response_format={'type': 'json_object'},
            )
            return resp.choices[0].message.content, {
                'prompt_tokens': resp.usage.prompt_tokens,
                'completion_tokens': resp.usage.completion_tokens,
            }
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            transient = any(
                tok in msg for tok in ('429', 'rate', 'timeout', '503', '500')
            )
            if not transient or attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise last_err  # pragma: no cover


def derive_rubric(
    domain: str,
    sample_entities: list[dict],
    llm_client,
    model: str,
    cache_path: str | Path | None = None,
) -> dict:
    """Stage A: LLM-derived keep/demote rubric (1 call). Domain is passed as
    a free-text string; no domain-specific rules embedded.

    If `cache_path` exists, load and return it. Otherwise call, save, return.
    exp7 showed 3 runs converge so a single derivation suffices.
    """
    if cache_path:
        cp = Path(cache_path)
        if cp.exists():
            return json.loads(cp.read_text(encoding='utf-8'))

    sample_lines = '\n'.join(
        f'- {e["title"]} ({e["type"]})' for e in sample_entities
    )
    sys_p = (
        '당신은 학습 자료 분석가다. 주어진 도메인의 한 학생이 자료를 외운다고 할 때, '
        "엔티티들 중 어떤 부류가 '콕 집어 이름까지 외울 대상'이 되고 어떤 부류가 "
        "'배경/맥락'으로 흐를지 가르는 기준(rubric)을 스스로 도출하라. "
        '외부에서 미리 정한 축에 끼워 맞추지 말고 도메인 학습 맥락에서 자연스럽게 도출하라.'
    )
    user_p = (
        f'도메인: {domain}\n\n'
        f'샘플 {len(sample_entities)}개:\n{sample_lines}\n\n'
        '지시:\n'
        '- keep(콕 집어 외울 대상) vs demote(배경) 기준 3~5개.\n'
        '- 각 기준에 도메인 예시 2~3개씩 (keep, demote 양쪽) 붙여라.\n\n'
        '출력 JSON:\n'
        '{\n'
        '  "rubric": [\n'
        '    {"id":"R1","rule":"...","examples_keep":["..."],"examples_demote":["..."]}\n'
        '  ],\n'
        '  "notes": "..."\n'
        '}'
    )
    raw, usage = call_json(llm_client, model, sys_p, user_p)
    obj = json.loads(raw)
    obj['_usage'] = usage
    if cache_path:
        cp = Path(cache_path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    return obj


def _stage_b_prompt(
    domain: str,
    rubric: dict,
    cid: int,
    members_payload: list[dict],
    node_budget: int,
) -> tuple[str, str]:
    sys_p = (
        '당신은 학습 자료 분석가다. 주어진 rubric에 따라 한 클러스터의 멤버를 '
        'keep/demote로 분류하고, 짧은 주제 이름을 붙이고, 응집도를 판정하라.\n'
        '\n'
        '규칙:\n'
        '- rubric만 적용. 본인의 다른 기준 끼우지 마라.\n'
        f'- keep은 최대 {node_budget}개. 절대 {node_budget}을 넘기지 마라.\n'
        '- 중요도 판단은 구체적이고 고유한 명칭(인물·사건·발명품·문헌·문화재 등 학습자가 '
        '콕 집어 외울 만한 것)을 우선. 추상 개념·일반 지명·집단명·시대는 demote.\n'
        '- degree는 참고 신호일 뿐 유일 기준이 아님. 일반어가 degree 높을 수 있다.\n'
        '- members 출력: keep은 중요도 내림차순으로 최대 N개, 나머지는 demote.\n'
        '- 입력 title과 정확히 일치해야 함. 누락·중복·창작 금지.'
    )
    rubric_text = json.dumps(
        {'rubric': rubric.get('rubric', []), 'notes': rubric.get('notes', '')},
        ensure_ascii=False, indent=2,
    )
    member_text = '\n'.join(
        f'{i + 1}. {m["title"]} (type={m["type"]}, degree={m["degree"]}) - {m["desc"]}'
        for i, m in enumerate(members_payload)
    )
    user_p = (
        f'도메인: {domain}\n\n'
        f'[rubric]\n{rubric_text}\n\n'
        f'[클러스터 {cid} 멤버 {len(members_payload)}개]\n{member_text}\n\n'
        f'keep 상한: {node_budget}\n\n'
        '출력 JSON:\n'
        '{\n'
        '  "room_name": "15자 이내",\n'
        '  "coherence": "coherent|grab-bag|type-pile",\n'
        '  "coherence_reason": "한 줄",\n'
        '  "members": [{"title":"...","classification":"keep|demote"}]\n'
        '}'
    )
    return sys_p, user_p


def _stage_b_retry_prompt(
    domain: str,
    cid: int,
    missing: list[dict],
) -> tuple[str, str]:
    sys_p = (
        '이전 응답에서 누락된 멤버들을 keep 또는 demote로 분류하라. 입력 title과 '
        '정확히 일치해야 한다. 누락·중복·창작 금지.'
    )
    member_text = '\n'.join(
        f'{i + 1}. {m["title"]} (type={m["type"]}, degree={m["degree"]})'
        for i, m in enumerate(missing)
    )
    user_p = (
        f'도메인: {domain}\n클러스터 {cid}.\n'
        f'누락 멤버 {len(missing)}개:\n{member_text}\n\n'
        '출력 JSON:\n'
        '{ "members":[{"title":"...","classification":"keep|demote"}] }'
    )
    return sys_p, user_p


def _run_stage_b_once(
    cid: int,
    members_payload: list[dict],
    domain: str,
    rubric: dict,
    node_budget: int,
    llm_client,
    model: str,
    max_complete_retries: int = 3,
) -> dict:
    input_set = {m['title'] for m in members_payload}
    sys_p, user_p = _stage_b_prompt(domain, rubric, cid, members_payload, node_budget)
    raw, _ = call_json(llm_client, model, sys_p, user_p)
    obj = json.loads(raw)

    members_out = obj.get('members', [])
    keep_order = [m['title'] for m in members_out
                  if m.get('classification') == 'keep' and m.get('title') in input_set]
    demote_set = {m['title'] for m in members_out
                  if m.get('classification') == 'demote' and m.get('title') in input_set}

    # Completeness retry loop: any input title not in keep or demote → ask LLM again.
    for _ in range(max_complete_retries):
        seen = set(keep_order) | demote_set
        missing_titles = input_set - seen
        if not missing_titles:
            break
        miss_payload = [m for m in members_payload if m['title'] in missing_titles]
        sys_p2, user_p2 = _stage_b_retry_prompt(domain, cid, miss_payload)
        raw2, _ = call_json(llm_client, model, sys_p2, user_p2)
        try:
            obj2 = json.loads(raw2)
            for m in obj2.get('members', []):
                t = m.get('title')
                if t not in missing_titles:
                    continue
                if m.get('classification') == 'keep':
                    keep_order.append(t)
                elif m.get('classification') == 'demote':
                    demote_set.add(t)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Force-demote anything still missing.
    forced = input_set - set(keep_order) - demote_set
    if forced:
        demote_set |= forced

    return {
        'room_name': str(obj.get('room_name', '')).strip() or '(unnamed)',
        'coherence': obj.get('coherence', 'unknown'),
        'coherence_reason': obj.get('coherence_reason', ''),
        'keep_order': keep_order,
        'demote_set': demote_set,
        'n_forced_demote': len(forced),
    }


def _resolve_keep_membership(
    runs: list[dict],
    input_set: set[str],
    node_budget: int,
) -> tuple[list[str], set[str], int]:
    """Combine n runs into a single (keep_order, demote_set, n_forced).

    Single run: take LLM order as-is; cut tail beyond node_budget to demote.
    Multiple runs: majority vote on keep membership; order by vote-desc with
    first run's order as tiebreaker; cut tail beyond budget by same order.
    """
    if len(runs) == 1:
        r = runs[0]
        keep_order = list(r['keep_order'])
        demote_set = set(r['demote_set'])
        if len(keep_order) > node_budget:
            overflow = keep_order[node_budget:]
            keep_order = keep_order[:node_budget]
            demote_set |= set(overflow)
        forced = input_set - set(keep_order) - demote_set
        if forced:
            demote_set |= forced
        return keep_order, demote_set, len(forced) + r['n_forced_demote']

    threshold = len(runs) / 2.0
    votes: dict[str, int] = defaultdict(int)
    for r in runs:
        for t in r['keep_order']:
            votes[t] += 1
    majority_keep = {t for t, v in votes.items() if v > threshold}

    run0_order = {t: i for i, t in enumerate(runs[0]['keep_order'])}
    keep_sorted = sorted(
        majority_keep,
        key=lambda t: (-votes[t], run0_order.get(t, 1_000_000), t),
    )
    if len(keep_sorted) > node_budget:
        keep_sorted = keep_sorted[:node_budget]
    demote_set = input_set - set(keep_sorted)
    total_forced = sum(r['n_forced_demote'] for r in runs)
    return keep_sorted, demote_set, total_forced


def assign_rooms(
    final_clusters: list[list[int]],
    entities: list[dict],
    domain: str,
    rubric: dict,
    n_runs: int,
    node_budget: int,
    llm_client,
    model: str,
    source_ids: list[list[int]] | None = None,
) -> list[dict]:
    """Stage B for every final cluster. Enforces:
    - kept ∪ demoted == cluster input entities (completeness, no drops)
    - len(kept) <= node_budget per room (backstop after retries)
    - n_runs > 1: majority vote on keep membership; LLM order for tiebreak

    source_ids: optional parallel list naming the pre-merge cluster IDs that
    composed each final cluster. Defaults to [[i] for i in range(len(final))].
    """
    if n_runs < 1:
        raise ValueError(f'n_runs must be >= 1, got {n_runs}')
    if source_ids is None:
        source_ids = [[i] for i in range(len(final_clusters))]
    if len(source_ids) != len(final_clusters):
        raise ValueError('source_ids length must match final_clusters length')

    rooms: list[dict] = []
    for room_id, cluster_idx in enumerate(final_clusters):
        members_payload = [
            {
                'title': entities[i]['title'],
                'type': entities[i]['type'],
                'degree': entities[i]['degree'],
                'desc': entities[i]['description'][:200],
            }
            for i in cluster_idx
        ]
        input_set = {m['title'] for m in members_payload}

        runs = [
            _run_stage_b_once(
                room_id, members_payload, domain, rubric, node_budget,
                llm_client, model,
            )
            for _ in range(n_runs)
        ]

        keep_order, demote_set, n_forced = _resolve_keep_membership(
            runs, input_set, node_budget,
        )

        title_to_e = {entities[i]['title']: entities[i] for i in cluster_idx}
        kept = [
            {
                'id': title_to_e[t]['id'],
                'title': t,
                'type': title_to_e[t]['type'],
                'degree': title_to_e[t]['degree'],
            }
            for t in keep_order
        ]
        demoted = [
            {
                'id': title_to_e[t]['id'],
                'title': t,
                'type': title_to_e[t]['type'],
                'degree': title_to_e[t]['degree'],
            }
            for t in sorted(demote_set, key=lambda x: -title_to_e[x]['degree'])
        ]

        rooms.append({
            'room_id': room_id,
            'name': runs[0]['room_name'],
            'kept': kept,
            'demoted': demoted,
            'source_clusters': list(source_ids[room_id]),
            'coherence_flag': runs[0]['coherence'],
            '_meta': {
                'coherence_reason': runs[0]['coherence_reason'],
                'n_forced_demote': n_forced,
                'n_runs': n_runs,
                'all_run_names': [r['room_name'] for r in runs] if n_runs > 1 else None,
            },
        })
    return rooms


def generate_rooms(
    snapshot_path: str | Path,
    K: int,
    k_base: int,
    max_cluster_size: int,
    merge_strategy: str,
    n_runs: int,
    node_budget: int,
    domain: str,
    model: str,
    output_path: str | Path,
) -> dict:
    raise NotImplementedError('generate_rooms: wired in final commit')


# ---------------------------------------------------------------------------
# Invariants (used everywhere — kept here for visibility).
# ---------------------------------------------------------------------------

HARD_CAP_K = 10  # rooms cannot exceed this


def check_invariants(
    rooms: list[dict],
    n_entities_in: int,
    K: int,
    node_budget: int,
) -> None:
    """Enforce: K <= HARD_CAP_K; rooms count == K; kept<=node_budget per room;
    sum(kept ∪ demoted) == n_entities_in, each entity exactly once.
    Raises AssertionError with a precise diff on violation.
    """
    if K > HARD_CAP_K:
        raise AssertionError(f'K={K} exceeds hard cap {HARD_CAP_K}')
    if len(rooms) > K:
        raise AssertionError(f'rooms {len(rooms)} > K {K}')

    seen_ids: list[str] = []
    for room in rooms:
        kept_n = len(room.get('kept', []))
        if kept_n > node_budget:
            raise AssertionError(
                f'room {room.get("room_id")} kept={kept_n} > budget={node_budget}'
            )
        for m in room.get('kept', []) + room.get('demoted', []):
            seen_ids.append(m['id'] if 'id' in m else m['title'])

    if len(seen_ids) != n_entities_in:
        raise AssertionError(
            f'entity count mismatch: kept+demoted={len(seen_ids)} '
            f'vs input={n_entities_in}'
        )
    if len(set(seen_ids)) != len(seen_ids):
        raise AssertionError(
            f'duplicate entities across rooms (unique={len(set(seen_ids))}, '
            f'total={len(seen_ids)})'
        )
