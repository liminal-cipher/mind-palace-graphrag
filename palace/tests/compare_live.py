"""라이브(캐시 miss) 검증 비교.

핵심 확인:
  (1) 측우기·자격루·앙부일구·혼천의가 골든과 같은 방(room 0)에 demote로 남는가
  (2) room 4(+2) 외에 다른 방은 변화 없는가 (room_id, kept 집합)

Usage:
    python palace/tests/compare_live.py \
        [--golden palace/tests/golden/repro_run3_K6_toc.json] \
        [--live   palace/tests/runs/repro_run3_K6_toc_live/repro_run3_K6_toc.json]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

TARGETS = ['측우기', '자격루', '앙부일구', '혼천의']


def find_in(spec: dict, title: str) -> tuple[int | None, str, str]:
    for r in spec['rooms']:
        for st, lst in (('kept', r.get('kept', [])), ('demoted', r.get('demoted', []))):
            for e in lst:
                if e['title'] == title:
                    return (
                        r.get('room_id'),
                        (r.get('_meta') or {}).get('section_name', ''),
                        st,
                    )
    return None, '', 'missing'


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--golden', default='palace/tests/golden/repro_run3_K6_toc.json')
    ap.add_argument('--live',
                    default='palace/tests/runs/repro_run3_K6_toc_live/repro_run3_K6_toc.json')
    args = ap.parse_args()
    g_path = Path(args.golden) if Path(args.golden).is_absolute() else REPO / args.golden
    l_path = Path(args.live) if Path(args.live).is_absolute() else REPO / args.live
    G = json.loads(g_path.read_text(encoding='utf-8'))
    L = json.loads(l_path.read_text(encoding='utf-8'))

    # (1) Four artifact entities: room id + status in both runs
    print('=== (1) 4대 천문기상기 (측우기·자격루·앙부일구·혼천의) ===')
    print(f'{"title":<8} {"G_room":>6} {"G_status":<9} {"L_room":>6} {"L_status":<9} {"same?":<6}')
    all_room0_demote_match = True
    for t in TARGETS:
        gr, _, gst = find_in(G, t)
        lr, _, lst = find_in(L, t)
        same = (gr == lr) and (gst == lst)
        if not (gr == 0 and gst == 'demoted' and lr == 0 and lst == 'demoted'):
            all_room0_demote_match = False
        print(f'{t:<8} {str(gr):>6} {gst:<9} {str(lr):>6} {lst:<9} {"yes" if same else "NO"}')
    print(f'\n  all four = room 0 / demoted in both: '
          f'{"YES" if all_room0_demote_match else "NO"}')

    # (2) Per-room delta: which rooms differ from golden
    print()
    print('=== (2) 방별 변화 (room_id별 kept 집합 비교) ===')
    print(f'{"room":<4} {"name(G)":<22} {"name(L)":<22} '
          f'{"k(G)":>4} {"k(L)":>4} {"jacc":>6} '
          f'{"only_G":<28} {"only_L":<28}')
    changed_rooms = []
    for gr, lr in zip(G['rooms'], L['rooms']):
        gk = set(k['title'] for k in gr.get('kept', []))
        lk = set(k['title'] for k in lr.get('kept', []))
        inter = gk & lk
        union = gk | lk
        jacc = (len(inter) / len(union)) if union else 1.0
        only_g = sorted(gk - lk)
        only_l = sorted(lk - gk)
        name_g = (gr.get('name') or '')[:20]
        name_l = (lr.get('name') or '')[:20]
        print(f'{gr["room_id"]:<4} {name_g:<22} {name_l:<22} '
              f'{len(gk):>4} {len(lk):>4} {jacc:>6.3f} '
              f'{str(only_g)[:26]:<28} {str(only_l)[:26]:<28}')
        if only_g or only_l:
            changed_rooms.append(gr['room_id'])
    print(f'\n  rooms that changed: {changed_rooms or "(none)"}')
    only_room4 = changed_rooms == [4]
    print(f'  changed == [room 4] only: {"YES" if only_room4 else "NO"}')

    # Totals
    print()
    print('=== 합계 ===')
    gk = sum(len(r.get('kept', [])) for r in G['rooms'])
    lk = sum(len(r.get('kept', [])) for r in L['rooms'])
    gd = sum(len(r.get('demoted', [])) for r in G['rooms'])
    ld = sum(len(r.get('demoted', [])) for r in L['rooms'])
    print(f'kept_total:    golden={gk}  live={lk}  diff={lk - gk:+d}')
    print(f'demoted_total: golden={gd}  live={ld}  diff={ld - gd:+d}')
    print(f'sum:           golden={gk + gd}  live={lk + ld}')

    print()
    if all_room0_demote_match and only_room4:
        print('PASS: 4대 천문기상기 모두 골든과 같은 방(0)에 demote로 남음, '
              '변화는 room 4 한 방에 국한됨.')
        return 0
    print('REVIEW: 위 표 확인 필요.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
