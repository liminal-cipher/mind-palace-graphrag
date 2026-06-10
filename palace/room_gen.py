"""TOC-arm slice of exp10_room_gen/room_gen.py.

Keeps: snapshot loader, Azure transport (call_json, make_azure_client),
Stage A (derive_rubric), Stage B (assign_rooms + helpers), invariant
check. Drops the GRAPH-arm clustering/merge code (base_cluster,
split_oversized, merge_to_k, generate_rooms, etc.) — palace does not
build rooms from embeddings.

Domain-agnostic: domain is a free-text string passed into prompts.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import lancedb
import numpy as np
import pandas as pd


HARD_CAP_K = 10


def load_snapshot(path: str | Path) -> tuple[list[dict], dict]:
    """Load entities + 1536-dim embeddings from a GraphRAG snapshot directory.

    Returns (entities, meta). Raises if any entity is missing a vector.
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


def make_azure_client():
    """Build Azure OpenAI client from GRAPHRAG_API_KEY / GRAPHRAG_API_BASE env."""
    from openai import AzureOpenAI
    api_key = os.environ.get('GRAPHRAG_API_KEY')
    if not api_key:
        raise SystemExit('GRAPHRAG_API_KEY not set')
    api_base = os.environ.get('GRAPHRAG_API_BASE')
    if not api_base:
        raise SystemExit('GRAPHRAG_API_BASE not set')
    return AzureOpenAI(
        azure_endpoint=api_base,
        api_key=api_key,
        api_version='2024-12-01-preview',
    )


def call_json(
    client,
    model: str,
    sys_p: str,
    user_p: str,
    max_retries: int = 6,
) -> tuple[str, dict]:
    """Azure OpenAI JSON-mode chat at temp=0 with exponential backoff."""
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
    """Stage A: LLM-derived keep/demote rubric (1 call). If cache_path exists,
    load and return it. Otherwise call, save, return.
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
        '당신은 학습 자료 분석가다. 주어진 rubric에 따라 한 클러스터에서 keep할 '
        '멤버만 골라 출력하고, 짧은 주제 이름과 응집도를 판정하라.\n'
        '\n'
        '규칙:\n'
        '- rubric만 적용. 본인의 다른 기준 끼우지 마라.\n'
        f'- keep은 최대 {node_budget}개. 절대 {node_budget}을 넘기지 마라.\n'
        '- 중요도 판단은 구체적이고 고유한 명칭(인물·사건·발명품·문헌·문화재 등 학습자가 '
        '콕 집어 외울 만한 것)을 우선. 추상 개념·일반 지명·집단명·시대는 demote.\n'
        '- degree는 참고 신호일 뿐 유일 기준이 아님. 일반어가 degree 높을 수 있다.\n'
        '- keep_titles는 중요도 내림차순. 입력 title과 정확히 일치해야 함. 창작 금지.\n'
        '- demote는 출력에 안 넣어도 됨 (시스템이 keep 외 멤버를 자동 demote로 처리).'
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
        f'  "keep_titles": ["중요도 1위", "2위", ...]   // 최대 {node_budget}개\n'
        '}'
    )
    return sys_p, user_p


def _stage_b_cache_key(model: str, sys_p: str, user_p: str) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(model.encode('utf-8'))
    h.update(b'\x1f')
    h.update(sys_p.encode('utf-8'))
    h.update(b'\x1f')
    h.update(user_p.encode('utf-8'))
    return h.hexdigest()


def _run_stage_b_once(
    cid: int,
    members_payload: list[dict],
    domain: str,
    rubric: dict,
    node_budget: int,
    llm_client,
    model: str,
    max_retries_on_empty: int = 2,
    stage_b_cache_dir: str | Path | None = None,
) -> dict:
    """One Stage-B call. Hash-keyed cache makes reruns byte-identical."""
    input_set = {m['title'] for m in members_payload}
    sys_p, user_p = _stage_b_prompt(domain, rubric, cid, members_payload, node_budget)

    cache_dir = Path(stage_b_cache_dir) if stage_b_cache_dir else None
    cache_key = _stage_b_cache_key(model, sys_p, user_p) if cache_dir else None
    cache_path = (cache_dir / f'{cache_key}.json') if cache_dir else None

    obj: dict = {}
    keep_order: list[str] = []
    hallucinated: list[str] = []

    for attempt in range(max_retries_on_empty + 1):
        cache_hit = (
            cache_path is not None and cache_path.exists() and attempt == 0
        )
        if cache_hit:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            raw = cached['raw']
        else:
            raw, _ = call_json(llm_client, model, sys_p, user_p)
            if cache_path is not None:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({'raw': raw, 'model': model}, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = {}

        keep_raw = obj.get('keep_titles', []) if isinstance(obj, dict) else []
        keep_order = []
        seen_keep: set[str] = set()
        hallucinated = []
        for t in keep_raw:
            if not isinstance(t, str):
                continue
            if t in input_set:
                if t not in seen_keep:
                    keep_order.append(t)
                    seen_keep.add(t)
            else:
                hallucinated.append(t)

        if cache_hit:
            break
        if keep_order or not input_set:
            break

    demote_set = input_set - set(keep_order)

    return {
        'room_name': str(obj.get('room_name', '')).strip() or '(unnamed)',
        'coherence': obj.get('coherence', 'unknown'),
        'coherence_reason': obj.get('coherence_reason', ''),
        'keep_order': keep_order,
        'demote_set': demote_set,
        'n_forced_demote': 0,
        'n_hallucinated': len(hallucinated),
    }


def _resolve_keep_membership(
    runs: list[dict],
    input_set: set[str],
    node_budget: int,
) -> tuple[list[str], set[str], int]:
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
    stage_b_cache_dir: str | Path | None = None,
) -> list[dict]:
    """Stage B for every final cluster."""
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
                stage_b_cache_dir=stage_b_cache_dir,
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
                'n_hallucinated': sum(r.get('n_hallucinated', 0) for r in runs),
                'n_runs': n_runs,
                'all_run_names': [r['room_name'] for r in runs] if n_runs > 1 else None,
            },
        })
    return rooms


def check_invariants(
    rooms: list[dict],
    n_entities_in: int,
    K: int,
    node_budget: int,
) -> None:
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
