"""Build 12 K=6 TOC palaces (4 Stage-B models * 3 runs) with everything
else held constant: same TOC sections, same char-overlap assignment,
same pos_first_fine order, same rubric (cached), same node_budget=20.
Only the Stage B model and run index change. Stage B cache bypassed
on every call so each run is an independent LLM trip.

For gpt-5.* deployments, temperature is unsupported (Azure forces
default=1) so this wrapper monkey-patches room_gen.call_json with a
version that omits temperature and adds reasoning_effort='low' for
gpt-5* models. gpt-4.1* keeps temperature=0.

Outputs (under results/rooms/):
    repro_run3_K6_toc.<slug>.run<N>.json
    repro_run3_K6_toc.<slug>.run<N>.palace.json
where slug ∈ {gpt41mini, gpt41, gpt54mini, gpt54} and N ∈ {1,2,3}.

Reports a summary table at the end. Does not modify the original
pipeline files. To rerun, just delete the .json outputs and re-execute.
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'results' / 'exp17_generalization'))
sys.path.insert(0, str(REPO / 'results' / 'exp10_room_gen'))
sys.path.insert(0, str(REPO / 'results' / 'node_order_probe'))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(REPO / '.env')

import pandas as pd  # noqa: E402

from build import (  # noqa: E402
    absorb_empty_rooms,
    apply_keep_demote,
    attach_positions,
    build_toc_rooms,
    convert_toc_to_common_schema,
)
import node_metrics  # noqa: E402
from room_gen import derive_rubric, load_snapshot, make_azure_client  # noqa: E402
import room_gen  # noqa: E402
import export_palace  # noqa: E402


BASE_RUN_ID = 'repro_run3_K6_toc'
CORPUS = REPO / 'input' / '국사교과서_조선_본문_정제.txt'
SNAPSHOT = REPO / 'results' / 'snapshots' / 'repro_run3'
SNAPSHOT_REL = 'results/snapshots/repro_run3'
ROOMS_DIR = REPO / 'results' / 'rooms'
TOC_OUT = ROOMS_DIR / f'{BASE_RUN_ID}.toc_llm.json'
RUBRIC_CACHE = REPO / 'cache' / 'exp10_room_gen' / 'rubric_repro_run3_toc.json'

K = 6
NODE_BUDGET = 20
DOMAIN = '조선 전기 한국사 (건국·통치제도·문화·사림·왜란·붕당·실학)'
TARGETS = ['측우기', '자격루', '앙부일구', '혼천의']

MODELS = [
    ('gpt41mini', 'gpt-4.1-mini', 'temp0'),
    ('gpt41', 'gpt-4.1', 'temp0'),
    ('gpt54mini', 'gpt-5.4-mini', 'reasoning'),
    ('gpt54', 'gpt-5.4', 'reasoning'),
]
N_RUNS = 3
SUMMARY_OUT = REPO / 'build_model_compare_summary.json'


def patched_call_json(client, model, sys_p, user_p, max_retries=6):
    """Replacement for room_gen.call_json that adapts to gpt-5* (no
    temperature, reasoning_effort='low') while keeping gpt-4.1* on temp=0.
    Same backoff behavior on transient errors as the original.
    """
    delay = 2.0
    last_err = None
    is_reasoning = model.startswith('gpt-5')
    for attempt in range(max_retries):
        try:
            kwargs = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': sys_p},
                    {'role': 'user', 'content': user_p},
                ],
                'response_format': {'type': 'json_object'},
            }
            if is_reasoning:
                kwargs['reasoning_effort'] = 'low'
            else:
                kwargs['temperature'] = 0
            resp = client.chat.completions.create(**kwargs)
            usage = {
                'prompt_tokens': resp.usage.prompt_tokens,
                'completion_tokens': resp.usage.completion_tokens,
            }
            details = getattr(resp.usage, 'completion_tokens_details', None)
            if details is not None:
                rt = getattr(details, 'reasoning_tokens', None)
                if rt is not None:
                    usage['reasoning_tokens'] = rt
            return resp.choices[0].message.content, usage
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            transient = any(tok in msg for tok in ('429', 'rate', 'timeout', '503', '500'))
            if not transient or attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise last_err


room_gen.call_json = patched_call_json


def stop_if_missing() -> None:
    missing = []
    if not CORPUS.exists():
        missing.append(str(CORPUS.relative_to(REPO)))
    if not TOC_OUT.exists():
        missing.append(str(TOC_OUT.relative_to(REPO)))
    if not RUBRIC_CACHE.exists():
        missing.append(str(RUBRIC_CACHE.relative_to(REPO)))
    for name in ('entities.parquet', 'text_units.parquet', 'documents.parquet'):
        if not (SNAPSHOT / name).exists():
            missing.append(f'{SNAPSHOT_REL}/{name}')
    if missing:
        print('STOP: missing inputs')
        for m in missing:
            print(f'  - {m}')
        sys.exit(2)


def build_once(
    *, model_slug: str, model_name: str, run_idx: int,
    toc_spec_template: dict, entities: list[dict], rubric: dict, client,
) -> dict:
    """One model x run build. Returns a summary row for reporting."""
    run_id = f'{BASE_RUN_ID}.{model_slug}.run{run_idx}'
    rooms_path = ROOMS_DIR / f'{run_id}.json'
    palace_existing = ROOMS_DIR / f'{run_id}.palace.json'
    spec = copy.deepcopy(toc_spec_template)
    t0 = time.time()

    if palace_existing.exists() and rooms_path.exists():
        print(f'  [{run_id}] reuse existing palace.json')
        palace_path = palace_existing
        stats = {'fine': 0, 'fallback': 0, 'unresolved': 0}
    else:
        print(f'  [{run_id}] Stage B ({model_name})...')
        spec = apply_keep_demote(
            spec, entities, rubric, client,
            domain=DOMAIN, model=model_name, node_budget=NODE_BUDGET, n_runs=1,
            rubric_source_rel=str(RUBRIC_CACHE.relative_to(REPO)).replace('\\', '/'),
            stage_b_cache_dir=None,
        )
        rooms_json = convert_toc_to_common_schema(
            spec, run_id=run_id, domain=DOMAIN, snapshot_rel=SNAPSHOT_REL,
            model=model_name, node_budget=NODE_BUDGET,
            n_entities=len(entities), k=K,
        )
        rooms_json = absorb_empty_rooms(rooms_json)
        rooms_path.write_text(
            json.dumps(rooms_json, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        palace_path, stats = export_palace.export(run_id, SNAPSHOT, with_relationships=False)
    dt = time.time() - t0

    palace = json.loads(Path(palace_path).read_text(encoding='utf-8'))
    rooms = palace['rooms']
    keep_total = sum(r['kept_count'] for r in rooms)

    target_status: dict[str, dict] = {}
    for tgt in TARGETS:
        target_status[tgt] = {'state': 'missing', 'room_id': None, 'room_name': None, 'order_rank': None}
    for r in rooms:
        for k_item in r.get('kept', []):
            if k_item['title'] in TARGETS:
                # find order rank within kept (1-based by order asc)
                order_rank = None
                for i, kk in enumerate(r['kept']):
                    if kk['title'] == k_item['title']:
                        order_rank = i + 1
                        break
                target_status[k_item['title']] = {
                    'state': 'keep',
                    'room_id': r['id'],
                    'room_name': r['name'],
                    'order_rank': order_rank,
                }
        for d_item in r.get('demoted', []):
            if d_item['title'] in TARGETS and target_status[d_item['title']]['state'] == 'missing':
                target_status[d_item['title']] = {
                    'state': 'demote',
                    'room_id': r['id'],
                    'room_name': r['name'],
                    'order_rank': None,
                }

    print(f'  [{run_id}] done in {dt:.1f}s. keep_total={keep_total}')
    for tgt in TARGETS:
        st = target_status[tgt]
        if st['state'] == 'keep':
            print(f'    {tgt}: keep @ {st["room_id"]} ({st["room_name"]}) order_rank={st["order_rank"]}')
        elif st['state'] == 'demote':
            print(f'    {tgt}: demote @ {st["room_id"]} ({st["room_name"]})')
        else:
            print(f'    {tgt}: MISSING')

    return {
        'run_id': run_id,
        'model_slug': model_slug,
        'model_name': model_name,
        'run_idx': run_idx,
        'keep_total': keep_total,
        'palace_path': str(Path(palace_path).resolve().relative_to(REPO)).replace('\\', '/'),
        'targets': target_status,
        'duration_sec': round(dt, 2),
    }


def main() -> None:
    stop_if_missing()

    toc_payload = json.loads(TOC_OUT.read_text(encoding='utf-8'))
    sections = toc_payload['sections']

    text = CORPUS.read_text(encoding='utf-8')
    ent_df = pd.read_parquet(SNAPSHOT / 'entities.parquet')
    tu_df = pd.read_parquet(SNAPSHOT / 'text_units.parquet')
    entities, _ = load_snapshot(SNAPSHOT)
    n_ent = len(entities)
    print(f'entities loaded: {n_ent}')

    ent_metrics = node_metrics.compute_entity_metrics(ent_df, tu_df, text)

    print('building TOC arm (occurrence weighted by char overlap)...')
    toc_spec_template, _ = build_toc_rooms(entities, ent_df, tu_df, text, sections)
    print(f'  raw room sizes: {[r["size"] for r in toc_spec_template["rooms"]]}')

    print('sorting members by pos_first_fine...')
    toc_spec_template = attach_positions(
        toc_spec_template, ent_metrics, ent_df, tu_df, text,
    )

    rubric = json.loads(RUBRIC_CACHE.read_text(encoding='utf-8'))
    print(f'rubric items: {len(rubric.get("rubric", []))} (cached, derived under gpt-4.1-mini)')

    client = make_azure_client()

    rows: list[dict] = []
    for model_slug, model_name, _kind in MODELS:
        for run_idx in range(1, N_RUNS + 1):
            row = build_once(
                model_slug=model_slug, model_name=model_name, run_idx=run_idx,
                toc_spec_template=toc_spec_template,
                entities=entities, rubric=rubric, client=client,
            )
            rows.append(row)

    SUMMARY_OUT.write_text(
        json.dumps({
            'base_run_id': BASE_RUN_ID,
            'models': [{'slug': s, 'name': n, 'kind': k} for s, n, k in MODELS],
            'n_runs': N_RUNS,
            'node_budget': NODE_BUDGET,
            'k': K,
            'rubric_source': str(RUBRIC_CACHE.relative_to(REPO)).replace('\\', '/'),
            'targets': TARGETS,
            'rows': rows,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\nsaved summary: {SUMMARY_OUT.relative_to(REPO)}')

    print('\n=== keep_total per model x run ===')
    print('| 모델 | run1 | run2 | run3 |')
    print('|---|---|---|---|')
    for model_slug, model_name, _ in MODELS:
        triples = [r['keep_total'] for r in rows if r['model_slug'] == model_slug]
        print(f'| {model_name} | {triples[0]} | {triples[1]} | {triples[2]} |')

    print('\n=== target placement (room_id / order_rank | demote@room_id) ===')
    print('| 모델 | run | 측우기 | 자격루 | 앙부일구 | 혼천의 |')
    print('|---|---|---|---|---|---|')
    for r in rows:
        cells = []
        for tgt in TARGETS:
            st = r['targets'][tgt]
            if st['state'] == 'keep':
                cells.append(f'keep {st["room_id"]}#{st["order_rank"]}')
            elif st['state'] == 'demote':
                cells.append(f'demote {st["room_id"]}')
            else:
                cells.append('MISSING')
        print(f'| {r["model_name"]} | {r["run_idx"]} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |')


if __name__ == '__main__':
    main()
