"""exp17 Phase B step 3: corpus / extraction / pos_first_fine metrics.

Inputs (from results/exp17_generalization/):
    snapshot/{entities,relationships,text_units}.parquet
    snapshot/stats.json (timings)
    cache/                           (token usage scan)
    ../../input/ai_gyoan/AI_교안_정제.txt
    ../node_order_probe/node_metrics.py  (position helpers, reused as-is)

Output: results/exp17_generalization/metrics.json (+ stdout).

Records (no LLM, no embeddings, deterministic):
    corpus_chars, n_entities, n_relationships, n_text_units
    single_chunk_entity_ratio  -- |E with len(text_unit_ids)==1| / |E|
    pos_first_fine match rate  -- |E with fine_matched==1| / |E|
    timings  -- from stats.json (or None if absent)
    tokens   -- scanned from cache/ (prompt/completion + embeddings)
    cost_usd -- gpt-4.1-mini ($0.40 in, $1.60 out / M tokens),
                text-embedding-3-small ($0.02 / M tokens)
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SNAP = ROOT / 'snapshot'
CACHE = ROOT / 'cache'
CORPUS = REPO / 'input' / 'ai_gyoan' / 'AI_교안_정제.txt'
OUT = ROOT / 'metrics.json'

sys.path.insert(0, str(REPO / 'results' / 'node_order_probe'))
import node_metrics  # noqa: E402

# Prices ($ / M tokens)
PRICE_IN = 0.40
PRICE_OUT = 1.60
PRICE_EMB = 0.02


def scan_cache_tokens(cache_dir: Path) -> dict:
    """Walk cache/ JSONs and sum prompt_tokens / completion_tokens.

    Embeddings have no completion_tokens but their prompt_tokens count is
    the embedded text length. We bucket embedding vs completion by the
    presence of completion_tokens.
    """
    chat_in = 0
    chat_out = 0
    emb_in = 0
    n_chat = 0
    n_emb = 0
    if not cache_dir.exists():
        return {
            'cache_present': False,
            'chat': {'n_calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0},
            'embedding': {'n_calls': 0, 'prompt_tokens': 0},
        }
    for p in cache_dir.rglob('*'):
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        # graphrag cache shape: {"result": {"response": {..., "usage": {...}}}}
        # embeddings shape: {"result": {"response": {"usage": {...}}}} (no
        # completion_tokens) or similar; defensively try a few paths.
        usage = None
        if isinstance(obj, dict):
            res = obj.get('result')
            if isinstance(res, dict):
                resp = res.get('response')
                if isinstance(resp, dict):
                    usage = resp.get('usage')
                if usage is None:
                    usage = res.get('usage')
            if usage is None:
                usage = obj.get('usage')
        if not isinstance(usage, dict):
            continue
        ptok = int(usage.get('prompt_tokens', 0) or 0)
        ctok = int(usage.get('completion_tokens', 0) or 0)
        if ctok > 0:
            chat_in += ptok
            chat_out += ctok
            n_chat += 1
        else:
            emb_in += ptok
            n_emb += 1
    return {
        'cache_present': True,
        'chat': {'n_calls': n_chat, 'prompt_tokens': chat_in, 'completion_tokens': chat_out},
        'embedding': {'n_calls': n_emb, 'prompt_tokens': emb_in},
    }


def main() -> None:
    if not SNAP.exists():
        print(f'STOP: snapshot missing at {SNAP}; run snapshot.py first')
        sys.exit(2)

    text = CORPUS.read_text(encoding='utf-8')
    ent = pd.read_parquet(SNAP / 'entities.parquet')
    rel = pd.read_parquet(SNAP / 'relationships.parquet')
    tu = pd.read_parquet(SNAP / 'text_units.parquet')

    # single-chunk ratio: entities whose text_unit_ids list has length 1
    def n_units(x) -> int:
        if x is None:
            return 0
        try:
            return len(list(x))
        except TypeError:
            return 0

    n_units_series = ent['text_unit_ids'].apply(n_units)
    single = int((n_units_series == 1).sum())
    multi = int((n_units_series > 1).sum())
    zero = int((n_units_series == 0).sum())

    # Reuse node_metrics for position metrics on the *current* snapshot.
    rows = node_metrics.compute_entity_metrics(ent, tu, text)
    n_fine_matched = sum(r['fine_matched'] for r in rows)
    pos_first_unresolved = sum(1 for r in rows if r['pos_first'] < 0)

    # type column distribution
    if 'type' in ent.columns:
        type_dist = ent['type'].astype(str).value_counts().to_dict()
    else:
        type_dist = {}

    # timings: graphrag stats.json
    stats_path = SNAP / 'stats.json'
    timings = None
    if stats_path.exists():
        try:
            timings = json.loads(stats_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            timings = None

    tokens = scan_cache_tokens(CACHE)
    cost = {
        'chat_in_usd': round(tokens['chat']['prompt_tokens'] / 1_000_000 * PRICE_IN, 6),
        'chat_out_usd': round(tokens['chat']['completion_tokens'] / 1_000_000 * PRICE_OUT, 6),
        'embedding_usd': round(tokens['embedding']['prompt_tokens'] / 1_000_000 * PRICE_EMB, 6),
    }
    cost['total_usd'] = round(sum(cost.values()), 6)

    metrics = {
        'corpus': {
            'path': str(CORPUS.relative_to(REPO)).replace('\\', '/'),
            'chars': len(text),
        },
        'counts': {
            'entities': int(len(ent)),
            'relationships': int(len(rel)),
            'text_units': int(len(tu)),
        },
        'entity_text_unit_distribution': {
            'single_chunk': single,
            'multi_chunk': multi,
            'zero_chunk': zero,
            'single_chunk_ratio': round(single / len(ent), 4) if len(ent) else 0.0,
        },
        'pos_first_fine': {
            'fine_matched': int(n_fine_matched),
            'fine_match_rate': round(n_fine_matched / len(rows), 4) if rows else 0.0,
            'pos_first_unresolved': int(pos_first_unresolved),
        },
        'entity_type_distribution': {str(k): int(v) for k, v in type_dist.items()},
        'timings': timings,
        'tokens': tokens,
        'cost_usd': cost,
        'sources': {
            'snapshot': str(SNAP.relative_to(REPO)).replace('\\', '/'),
            'cache': str(CACHE.relative_to(REPO)).replace('\\', '/'),
            'node_metrics': 'results/node_order_probe/node_metrics.py',
        },
    }
    OUT.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
