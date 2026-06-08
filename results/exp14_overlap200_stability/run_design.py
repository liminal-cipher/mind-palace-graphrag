"""exp14 step-3 reimplementation: LLM-only room design from GraphRAG
communities + entities. N runs against a frozen input; each run is one
LLM call (temp=0). Run output: rooms + per-entity (room, visibility).

This is a faithful reimplementation of the overlap200 step-3 idea
(LLM designs ~6 learning-flow rooms with 4-level visibility), not a
re-execution of any teammate's code.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'results' / 'exp10_room_gen'))

from room_gen import call_json, make_azure_client  # noqa: E402

FROZEN_INPUT = Path('results/exp14_overlap200_stability/frozen_input.json')
OUT_DIR = Path('results/exp14_overlap200_stability')
DOMAIN = '한국사'
MODEL = 'gpt-4.1-mini'
TARGET_ROOM_COUNT = 6
VISIBILITY_LEVELS = ('core', 'supporting', 'search_only', 'background')


def _load_dotenv(path: str = '.env') -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


def build_prompts(blob: dict) -> tuple[str, str]:
    entities = blob['entities']
    communities = blob['communities']
    uncovered = blob.get('uncovered_entity_titles', [])

    title_to_meta = {e['title']: e for e in entities}

    com_lines = []
    for c in communities:
        rep_title = c.get('report_title') or '(no report title)'
        rep_sum = (c.get('report_summary') or '').strip()
        if len(rep_sum) > 600:
            rep_sum = rep_sum[:600] + '...'
        members = ', '.join(c['member_titles'])
        com_lines.append(
            f'### community {c["community_id"]} (size={c["size"]})\n'
            f'report_title: {rep_title}\n'
            f'summary: {rep_sum}\n'
            f'members: {members}'
        )
    com_block = '\n\n'.join(com_lines)

    ent_lines = []
    for e in entities:
        desc = (e['description'] or '').strip().replace('\n', ' ')
        if len(desc) > 200:
            desc = desc[:200] + '...'
        ent_lines.append(
            f'- {e["title"]} (type={e["type"]}, degree={e["degree"]}): {desc}'
        )
    ent_block = '\n'.join(ent_lines)

    uncovered_note = (
        f'\n참고: {len(uncovered)}개 엔티티는 어떤 level-0 커뮤니티에도 속하지 않는다. '
        f'그래도 학습 흐름상 의미가 있으면 적절한 방에 배치하고 visibility를 부여하라. '
        f'목록: {", ".join(uncovered)}'
        if uncovered else ''
    )

    sys_p = (
        f'당신은 학습 자료 설계자다. 도메인은 "{DOMAIN}"이다. '
        f'GraphRAG로 추출한 커뮤니티와 엔티티를 받아, 학습 흐름(시대·주제·인과)을 '
        f'중심으로 약 {TARGET_ROOM_COUNT}개의 "방"을 설계하라. 방 개수는 자료의 '
        f'자연스러운 단락이 다르면 ±2 범위에서 조정해도 된다.\n\n'
        f'모든 엔티티는 정확히 한 방에 배치되어야 한다. 누락·중복 금지. '
        f'각 엔티티에 4단계 visibility 중 하나를 부여하라:\n'
        f'  - core: 학습자가 콕 집어 외울 핵심 (인물·사건·발명품·문헌·문화재 등 고유 명칭)\n'
        f'  - supporting: 핵심을 잇는 보조 (제도·중요 개념·핵심 주변 인물)\n'
        f'  - search_only: 약한 보조 (검색했을 때만 노출되어도 충분한 것)\n'
        f'  - background: 배경 (시대·일반 지명·집단명·추상 개념)\n\n'
        f'게이트: 핵심을 강하게 지지하지 않는 보조성은 supporting 대신 search_only로 '
        f'내려라. supporting을 남발하지 말 것.\n\n'
        f'방 이름은 학습 흐름을 담은 한 줄(20자 이내). 입력 entity_title과 '
        f'정확히 일치해야 한다. 창작 금지. 출력은 JSON.'
    )

    user_p = (
        f'[커뮤니티 {len(communities)}개]\n{com_block}\n\n'
        f'[엔티티 {len(entities)}개]\n{ent_block}'
        f'{uncovered_note}\n\n'
        f'출력 JSON 스키마:\n'
        f'{{\n'
        f'  "rooms": [\n'
        f'    {{"id": 0, "title": "방 이름", "flow_note": "왜 이 방인지 한 줄"}},\n'
        f'    ...\n'
        f'  ],\n'
        f'  "assignments": {{\n'
        f'    "엔티티 제목": {{"room_id": 0, "visibility": "core"}},\n'
        f'    ...\n'
        f'  }}\n'
        f'}}\n\n'
        f'규칙:\n'
        f'- rooms[*].id는 0부터 연속.\n'
        f'- assignments의 키는 입력 엔티티 {len(entities)}개 전수. 빠뜨리지 마라.\n'
        f'- room_id는 rooms 안에 정의된 id 중 하나.\n'
        f'- visibility는 {VISIBILITY_LEVELS} 중 하나.'
    )
    _ = title_to_meta  # silence unused
    return sys_p, user_p


def parse_response(raw: str, entity_titles: set[str]) -> dict:
    obj = json.loads(raw)
    rooms = obj.get('rooms', [])
    asn = obj.get('assignments', {})

    room_ids = set()
    rooms_clean = []
    for r in rooms:
        rid = int(r['id'])
        room_ids.add(rid)
        rooms_clean.append({
            'id': rid,
            'title': str(r.get('title', '')).strip(),
            'flow_note': str(r.get('flow_note', '')).strip(),
        })

    assignments: dict[str, dict] = {}
    invalid_vis = 0
    invalid_room = 0
    hallucinated = 0
    for k, v in asn.items():
        if k not in entity_titles:
            hallucinated += 1
            continue
        rid = int(v.get('room_id', -1))
        vis = str(v.get('visibility', '')).strip()
        if rid not in room_ids:
            invalid_room += 1
            continue
        if vis not in VISIBILITY_LEVELS:
            invalid_vis += 1
            continue
        assignments[k] = {'room_id': rid, 'visibility': vis}

    missing = sorted(entity_titles - set(assignments.keys()))
    return {
        'rooms': rooms_clean,
        'assignments': assignments,
        '_diag': {
            'invalid_visibility': invalid_vis,
            'invalid_room': invalid_room,
            'hallucinated_titles': hallucinated,
            'missing_titles_count': len(missing),
            'missing_titles_sample': missing[:20],
        },
    }


def run_once(client, model: str, blob: dict, run_idx: int) -> dict:
    sys_p, user_p = build_prompts(blob)
    entity_titles = {e['title'] for e in blob['entities']}
    t0 = time.perf_counter()
    raw, usage = call_json(client, model, sys_p, user_p)
    dt = time.perf_counter() - t0
    parsed = parse_response(raw, entity_titles)
    parsed['_meta'] = {
        'run_idx': run_idx,
        'model': model,
        'temperature': 0,
        'wall_seconds': round(dt, 2),
        'prompt_tokens': usage.get('prompt_tokens'),
        'completion_tokens': usage.get('completion_tokens'),
        'frozen_input_path': str(FROZEN_INPUT),
    }
    return parsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--start', type=int, default=1)
    args = ap.parse_args()

    _load_dotenv()
    blob = json.loads(FROZEN_INPUT.read_text(encoding='utf-8'))
    print(f'frozen input: entities={len(blob["entities"])} '
          f'communities={len(blob["communities"])}')

    client = make_azure_client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(args.start, args.start + args.n):
        print(f'\n=== run {i} ===')
        spec = run_once(client, MODEL, blob, i)
        out = OUT_DIR / f'run{i}.json'
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
        rooms = spec['rooms']
        diag = spec['_diag']
        print(f'  rooms={len(rooms)} assignments={len(spec["assignments"])} '
              f'missing={diag["missing_titles_count"]} hallucinated={diag["hallucinated_titles"]} '
              f'invalid_room={diag["invalid_room"]} invalid_vis={diag["invalid_visibility"]} '
              f'wall={spec["_meta"]["wall_seconds"]}s '
              f'tokens={spec["_meta"]["prompt_tokens"]}+{spec["_meta"]["completion_tokens"]}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
