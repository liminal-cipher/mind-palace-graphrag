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
) -> list[list[int]]:
    raise NotImplementedError('merge_to_k: added in next commit')


def derive_rubric(
    domain: str,
    sample_entities: list[dict],
    llm_client,
    model: str,
    cache_path: str | Path | None = None,
) -> dict:
    raise NotImplementedError('derive_rubric: added in next commit')


def assign_rooms(
    final_clusters: list[list[int]],
    entities: list[dict],
    domain: str,
    rubric: dict,
    n_runs: int,
    node_budget: int,
    llm_client,
    model: str,
) -> list[dict]:
    raise NotImplementedError('assign_rooms: added in next commit')


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
