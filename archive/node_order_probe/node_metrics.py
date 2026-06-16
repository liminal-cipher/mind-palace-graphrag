"""node_order_probe shared metrics: position & weight per entity.

All numbers come from the existing snapshot (results/snapshots/repro_run3) and
source corpus (input/국사교과서_조선_본문_정제.txt). No LLM, no embeddings,
no randomness. Two runs return identical numbers.

Reuses the text_unit char-span derivation from exp08/exp15 (string-find of the
chunk's first 100/50 chars in the source text).

Public API:
    load_text() -> str
    build_text_unit_positions(tu_df, text) -> dict[uid] = (char_start, char_end, hr_id, length)
    compute_entity_metrics(ent_df, tu_df, text) -> list[dict]

Per-entity dict columns:
    entity, n_text_units, pos_first, pos_mode, pos_centroid,
    pos_first_fine, fine_matched, weight_count, graph_degree
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / 'results' / 'snapshots' / 'repro_run3'
TXT_PATH = REPO / 'input' / '국사교과서_조선_본문_정제.txt'


def load_text() -> str:
    return TXT_PATH.read_text(encoding='utf-8')


def build_text_unit_positions(tu_df: pd.DataFrame, text: str) -> dict:
    """Return {uid: (char_start, char_end, hr_id, length)}.

    Uses the exp08/exp15 string-find approach. text_units do not store a char
    offset, but each chunk's verbatim text appears once in the source corpus.
    """
    positions = {}
    for _, r in tu_df.iterrows():
        utext = str(r['text'])
        needle = utext[:100].strip()
        pos = text.find(needle) if needle else -1
        if pos < 0:
            needle = utext[:50].strip()
            pos = text.find(needle) if needle else -1
        end = pos + len(utext) if pos >= 0 else -1
        positions[r['id']] = (pos, end, int(r['human_readable_id']), len(utext))
    return positions


def _surface_variants(title: str) -> list[str]:
    """Generate surface variants for fine-grained matching.

    GraphRAG normalizes entity titles to upper case in some cases. For Korean
    text the title is usually the surface form already; we try the raw title
    and a stripped/space-collapsed variant.
    """
    title = str(title).strip()
    variants = [title]
    # collapsed whitespace
    collapsed = re.sub(r'\s+', '', title)
    if collapsed and collapsed not in variants:
        variants.append(collapsed)
    # title may carry trailing punctuation in some snapshots; try strip
    stripped = title.rstrip('.,;:')
    if stripped and stripped not in variants:
        variants.append(stripped)
    return variants


def _count_in_chunk(chunk_text: str, variants: list[str]) -> int:
    """Sum non-overlapping occurrence counts of all variants in the chunk."""
    total = 0
    for v in variants:
        if not v:
            continue
        total += chunk_text.count(v)
    return total


def _first_in_text(text: str, variants: list[str]) -> int:
    """Earliest char index where any variant appears, or -1."""
    best = -1
    for v in variants:
        if not v:
            continue
        pos = text.find(v)
        if pos < 0:
            continue
        if best < 0 or pos < best:
            best = pos
    return best


def compute_entity_metrics(
    ent_df: pd.DataFrame,
    tu_df: pd.DataFrame,
    text: str,
) -> list[dict]:
    positions = build_text_unit_positions(tu_df, text)
    uid_to_text = {r['id']: str(r['text']) for _, r in tu_df.iterrows()}

    rows = []
    for _, r in ent_df.iterrows():
        title = str(r['title'])
        variants = _surface_variants(title)
        uids = list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []
        weight_count = len(uids)
        graph_degree = int(r['degree']) if 'degree' in r else 0

        # per-chunk char_start (filter out chunks whose position was not found)
        chunk_info = []
        for uid in uids:
            cs, ce, hr_id, _length = positions.get(uid, (-1, -1, -1, 0))
            if cs < 0:
                continue
            count = _count_in_chunk(uid_to_text.get(uid, ''), variants)
            chunk_info.append({'uid': uid, 'cs': cs, 'hr': hr_id, 'count': count})

        # pos_first / pos_mode / pos_centroid
        if chunk_info:
            pos_first = min(ci['cs'] for ci in chunk_info)
            max_count = max(ci['count'] for ci in chunk_info)
            if max_count > 0:
                mode_cands = [ci for ci in chunk_info if ci['count'] == max_count]
                pos_mode = min(ci['cs'] for ci in mode_cands)
                total_w = sum(ci['count'] for ci in chunk_info)
                pos_centroid = sum(ci['count'] * ci['cs'] for ci in chunk_info) / total_w
            else:
                # surface match failed in every chunk; fall back to uniform weights
                pos_mode = pos_first
                pos_centroid = sum(ci['cs'] for ci in chunk_info) / len(chunk_info)
        else:
            pos_first = -1
            pos_mode = -1
            pos_centroid = -1.0

        # pos_first_fine: surface-search the source text directly
        fine_pos = _first_in_text(text, variants)
        fine_matched = fine_pos >= 0
        pos_first_fine = fine_pos if fine_matched else pos_first

        rows.append({
            'entity': title,
            'n_text_units': weight_count,
            'pos_first': pos_first,
            'pos_mode': pos_mode,
            'pos_centroid': round(pos_centroid, 2) if isinstance(pos_centroid, float) else pos_centroid,
            'pos_first_fine': pos_first_fine,
            'fine_matched': int(fine_matched),
            'weight_count': weight_count,
            'graph_degree': graph_degree,
        })
    return rows


def load_snapshot_frames(snapshot: Path = SNAPSHOT) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ent_df = pd.read_parquet(snapshot / 'entities.parquet')
    tu_df = pd.read_parquet(snapshot / 'text_units.parquet')
    rel_df = pd.read_parquet(snapshot / 'relationships.parquet')
    return ent_df, tu_df, rel_df


def tie_cluster_sizes(rows: list[dict], key: str = 'pos_first') -> Counter:
    """How many entities share the same pos_first/pos_mode value.

    Returns Counter{cluster_size: number_of_clusters_of_that_size}.
    """
    bucket = Counter(r[key] for r in rows if r[key] >= 0)
    sizes = Counter(bucket.values())
    return sizes
