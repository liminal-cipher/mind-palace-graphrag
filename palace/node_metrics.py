"""Position helpers for entity ordering.

Copied from results/node_order_probe/node_metrics.py, trimmed to the
helpers the palace TOC pipeline actually calls. Module-level SNAPSHOT
and TXT_PATH constants and the load_text / load_snapshot_frames /
tie_cluster_sizes helpers are dropped (probe-only).

Public API:
    build_text_unit_positions(tu_df, text) -> dict[uid] = (cs, ce, hr, length)
    compute_entity_metrics(ent_df, tu_df, text) -> list[dict]
    _surface_variants(title) -> list[str]
    _first_in_text(text, variants) -> int
"""
from __future__ import annotations

import re

import pandas as pd


def build_text_unit_positions(tu_df: pd.DataFrame, text: str) -> dict:
    """Return {uid: (char_start, char_end, hr_id, length)}.

    text_units do not store char offsets directly; each chunk's verbatim
    text appears once in the source corpus, so a string-find on the first
    100 (then 50) characters recovers the span deterministically.
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
    title = str(title).strip()
    variants = [title]
    collapsed = re.sub(r'\s+', '', title)
    if collapsed and collapsed not in variants:
        variants.append(collapsed)
    stripped = title.rstrip('.,;:')
    if stripped and stripped not in variants:
        variants.append(stripped)
    return variants


def _count_in_chunk(chunk_text: str, variants: list[str]) -> int:
    total = 0
    for v in variants:
        if not v:
            continue
        total += chunk_text.count(v)
    return total


def _first_in_text(text: str, variants: list[str]) -> int:
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

        chunk_info = []
        for uid in uids:
            cs, ce, hr_id, _length = positions.get(uid, (-1, -1, -1, 0))
            if cs < 0:
                continue
            count = _count_in_chunk(uid_to_text.get(uid, ''), variants)
            chunk_info.append({'uid': uid, 'cs': cs, 'hr': hr_id, 'count': count})

        if chunk_info:
            pos_first = min(ci['cs'] for ci in chunk_info)
            max_count = max(ci['count'] for ci in chunk_info)
            if max_count > 0:
                mode_cands = [ci for ci in chunk_info if ci['count'] == max_count]
                pos_mode = min(ci['cs'] for ci in mode_cands)
                total_w = sum(ci['count'] for ci in chunk_info)
                pos_centroid = sum(ci['count'] * ci['cs'] for ci in chunk_info) / total_w
            else:
                pos_mode = pos_first
                pos_centroid = sum(ci['cs'] for ci in chunk_info) / len(chunk_info)
        else:
            pos_first = -1
            pos_mode = -1
            pos_centroid = -1.0

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
