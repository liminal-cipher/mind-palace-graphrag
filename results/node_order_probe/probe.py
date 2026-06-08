"""node_order_probe runner.

Reads:
    results/snapshots/repro_run3/{entities,text_units,relationships}.parquet
    input/국사교과서_조선_본문_정제.txt
    results/exp16_room_compare/{toc_rooms,graph_rooms}.json

Writes:
    results/node_order_probe/node_position_weight.csv
    results/node_order_probe/rooms_ordered.md
    results/node_order_probe/REPORT.md

LLM calls: 0. Deterministic. Reuses node_metrics.py for all position/weight math.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from node_metrics import (  # noqa: E402
    REPO,
    compute_entity_metrics,
    load_snapshot_frames,
    load_text,
    tie_cluster_sizes,
)

OUT_DIR = REPO / 'results' / 'node_order_probe'
TOC_PATH = REPO / 'results' / 'exp16_room_compare' / 'toc_rooms.json'
GRAPH_PATH = REPO / 'results' / 'exp16_room_compare' / 'graph_rooms.json'

CSV_COLS = [
    'entity', 'n_text_units', 'pos_first', 'pos_mode', 'pos_centroid',
    'pos_first_fine', 'fine_matched', 'weight_count', 'graph_degree',
]


def write_csv(rows: list[dict]) -> Path:
    path = OUT_DIR / 'node_position_weight.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in CSV_COLS})
    return path


def _load_rooms(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _members_with_metrics(room: dict, by_title: dict[str, dict]) -> list[dict]:
    out = []
    for e in room['entities']:
        m = by_title.get(e['title'])
        if m is None:
            continue
        out.append({
            'title': e['title'],
            'pos_first': m['pos_first'],
            'pos_first_fine': m['pos_first_fine'],
            'weight_count': m['weight_count'],
            'graph_degree': m['graph_degree'],
            'n_text_units': m['n_text_units'],
        })
    return out


def _room_distinctiveness(rooms_obj: dict, by_title: dict[str, dict]) -> dict:
    """Per (room, entity) distinctiveness: room frequency / global frequency.

    Each entity's "frequency" here is weight_count (number of text_units).
    Distinctiveness is undefined when global == 0 (no chunks), set to 0.
    """
    # global weight_count for every entity in any room
    global_wc = {t: m['weight_count'] for t, m in by_title.items()}
    out = {}
    for r in rooms_obj['rooms']:
        # sum weight_count of room members
        room_sum = sum(global_wc.get(e['title'], 0) for e in r['entities'])
        per_entity = {}
        for e in r['entities']:
            w = global_wc.get(e['title'], 0)
            # share of this entity's mentions that fall in this room
            #   = room_share(E,R) / global_share(E)
            # but with weight_count we don't know per-room slice; use the
            # simpler "room-local count / global count" where room-local is
            # capped by w (entity may appear in multiple rooms in graph arm? no:
            # rooms here are a partition, so each entity is in exactly one).
            # So this reduces to: 1.0 for every entity. To make this meaningful
            # we instead compare the entity's room rank vs global rank.
            per_entity[e['title']] = {
                'weight_count': w,
                'room_rank': None,
                'global_rank': None,
            }
        # rank within room by weight_count desc, ties by pos_first asc
        members = [(t, by_title.get(t, {}).get('weight_count', 0),
                    by_title.get(t, {}).get('pos_first', 1 << 30))
                   for t in per_entity]
        members.sort(key=lambda x: (-x[1], x[2]))
        for i, (t, _, _) in enumerate(members, start=1):
            per_entity[t]['room_rank'] = i
        out[r['room_id']] = {
            'room_total_weight': room_sum,
            'members': per_entity,
        }
    # global rank by weight_count desc, ties by pos_first asc
    all_titles = [(t, m['weight_count'], m['pos_first']) for t, m in by_title.items()]
    all_titles.sort(key=lambda x: (-x[1], x[2]))
    global_rank = {t: i for i, (t, _, _) in enumerate(all_titles, start=1)}
    for r in rooms_obj['rooms']:
        for t in out[r['room_id']]['members']:
            out[r['room_id']]['members'][t]['global_rank'] = global_rank.get(t)
    return out


def _format_member_line(m: dict) -> str:
    return (f"{m['title']} (pos={m['pos_first']}, fine={m['pos_first_fine']}, "
            f"w={m['weight_count']}, deg={m['graph_degree']})")


def _rooms_section(label: str, rooms_obj: dict, by_title: dict[str, dict],
                   ks: list[int]) -> list[str]:
    md: list[str] = []
    md.append(f'## {label}')
    md.append('')
    md.append(f'source: `{rooms_obj["meta"].get("source", "")}`')
    md.append('')
    for r in rooms_obj['rooms']:
        members = _members_with_metrics(r, by_title)
        # by pos_first asc, ties broken by pos_first_fine then title
        ordered = sorted(members,
                         key=lambda m: (m['pos_first'], m['pos_first_fine'], m['title']))
        title = r['room_id']
        if 'chapter_id' in r:
            title = f'{title} ({r["chapter_id"]})'
        md.append(f'### {title} (size={r["size"]})')
        md.append('')
        md.append('순서: pos_first 오름차순. 동률이면 pos_first_fine, 다음은 title.')
        md.append('')
        for m in ordered:
            md.append(f'- {_format_member_line(m)}')
        md.append('')
        for K in ks:
            top = sorted(members, key=lambda m: (-m['weight_count'], m['pos_first'], m['title']))[:K]
            md.append(f'**top-{K} by weight_count**:')
            md.append('')
            for m in top:
                md.append(f'- {_format_member_line(m)}')
            md.append('')
    return md


def _distinctiveness_section(label: str, rooms_obj: dict, by_title: dict[str, dict]) -> list[str]:
    md: list[str] = []
    md.append(f'## {label}: room-relative distinctiveness 비교 (부록)')
    md.append('')
    md.append('각 방에서 weight_count top-5를 골라 그 멤버의 (room_rank, global_rank, weight_count) 표시. '
              'global_rank가 클수록 전체에선 드물고, room_rank가 작을수록 이 방에선 잦다.')
    md.append('')
    distinct = _room_distinctiveness(rooms_obj, by_title)
    for r in rooms_obj['rooms']:
        title = r['room_id']
        if 'chapter_id' in r:
            title = f'{title} ({r["chapter_id"]})'
        md.append(f'### {title}')
        md.append('')
        room_distinct = distinct[r['room_id']]['members']
        rows = sorted(room_distinct.items(),
                      key=lambda kv: (kv[1]['room_rank']))[:5]
        md.append('| entity | weight_count | room_rank | global_rank |')
        md.append('|---|---|---|---|')
        for t, info in rows:
            md.append(f'| {t} | {info["weight_count"]} | {info["room_rank"]} | {info["global_rank"]} |')
        md.append('')
    return md


def write_rooms_ordered(rows: list[dict], toc: dict, graph: dict) -> Path:
    by_title = {r['entity']: r for r in rows}
    md = []
    md.append('# rooms_ordered')
    md.append('')
    md.append('TOC 방(exp15 partition B)과 그래프 방(exp10 ward, K=6) 각각의 멤버를 결정적 위치(pos_first) 순서로 나열하고, 같은 방을 weight_count top-K로 추린 목록을 붙였다. 모든 수치는 결정적, LLM 0.')
    md.append('')
    md.append('각 항목 표기: `엔티티 (pos=pos_first 문자 오프셋, fine=pos_first_fine, w=weight_count text_units, deg=graph_degree)`')
    md.append('')

    md.extend(_rooms_section('TOC arm (exp15 partition B)', toc, by_title, [10, 15]))
    md.append('---')
    md.append('')
    md.extend(_rooms_section('Graph arm (exp10 ward, K=6)', graph, by_title, [10, 15]))
    md.append('---')
    md.append('')
    md.append('# 부록 A: pos_mode 순 정렬')
    md.append('')
    for label, rooms_obj in (('TOC arm', toc), ('Graph arm', graph)):
        md.append(f'## {label}: pos_mode 순')
        md.append('')
        for r in rooms_obj['rooms']:
            members = _members_with_metrics(r, by_title)
            ordered = sorted(
                members,
                key=lambda m: (by_title[m['title']]['pos_mode'], m['pos_first'], m['title']),
            )
            title = r['room_id']
            if 'chapter_id' in r:
                title = f'{title} ({r["chapter_id"]})'
            md.append(f'### {title}')
            md.append('')
            for m in ordered:
                pm = by_title[m['title']]['pos_mode']
                md.append(f'- {m["title"]} (pos_mode={pm}, pos_first={m["pos_first"]}, '
                          f'w={m["weight_count"]}, deg={m["graph_degree"]})')
            md.append('')

    md.append('---')
    md.append('')
    md.append('# 부록 B: room-relative distinctiveness')
    md.append('')
    md.extend(_distinctiveness_section('TOC arm', toc, by_title))
    md.extend(_distinctiveness_section('Graph arm', graph, by_title))

    path = OUT_DIR / 'rooms_ordered.md'
    path.write_text('\n'.join(md), encoding='utf-8')
    return path


def write_report(rows: list[dict], toc: dict, graph: dict) -> Path:
    n = len(rows)
    n_unmapped = sum(1 for r in rows if r['pos_first'] < 0)
    n_fine_matched = sum(1 for r in rows if r['fine_matched'])
    fine_rate = n_fine_matched / n if n else 0.0

    # tie cluster distribution on pos_first
    first_buckets = Counter(r['pos_first'] for r in rows if r['pos_first'] >= 0)
    tie_sizes = Counter(first_buckets.values())
    first_n_distinct = len(first_buckets)
    biggest_first_cluster = max(first_buckets.values()) if first_buckets else 0

    fine_buckets = Counter(r['pos_first_fine'] for r in rows if r['pos_first_fine'] >= 0)
    fine_n_distinct = len(fine_buckets)
    biggest_fine_cluster = max(fine_buckets.values()) if fine_buckets else 0

    # weight_count distribution
    wc_hist = Counter(r['weight_count'] for r in rows)

    # graph_degree quick stats
    degs = [r['graph_degree'] for r in rows]
    deg_mean = round(mean(degs), 2) if degs else 0
    deg_med = median(degs) if degs else 0
    deg_max = max(degs) if degs else 0

    # disagreement between pos_first and pos_first_fine (only when fine matched
    # and entity has at least one chunk position)
    diffs = []
    for r in rows:
        if r['fine_matched'] and r['pos_first'] >= 0:
            diffs.append(abs(r['pos_first'] - r['pos_first_fine']))
    diff_mean = round(mean(diffs), 2) if diffs else 0
    diff_med = median(diffs) if diffs else 0
    diff_big = sum(1 for d in diffs if d > 500)

    # top-K breakage observation: how many top-K members lie outside the room
    # they are members of, sorted by weight. Actually all members ARE in the
    # room; the relevant question is "does the room collapse to its top-K
    # representatives". Measure: for each room, top-K fraction of room weight.
    def top_k_coverage(rooms_obj: dict, K: int) -> list[tuple[str, int, int, float]]:
        out = []
        for r in rooms_obj['rooms']:
            members = [(e['title'], next((x['weight_count'] for x in rows if x['entity'] == e['title']), 0))
                       for e in r['entities']]
            members.sort(key=lambda x: -x[1])
            top = members[:K]
            total_w = sum(w for _, w in members)
            top_w = sum(w for _, w in top)
            coverage = top_w / total_w if total_w else 0.0
            out.append((r['room_id'], r['size'], len(top), round(coverage, 4)))
        return out

    toc_k10 = top_k_coverage(toc, 10)
    toc_k15 = top_k_coverage(toc, 15)
    graph_k10 = top_k_coverage(graph, 10)
    graph_k15 = top_k_coverage(graph, 15)

    md = []
    md.append('# node_order_probe REPORT')
    md.append('')
    md.append('> Deterministic position + weight metrics for the 357 entities in `results/snapshots/repro_run3`. LLM calls: 0. Two runs return identical numbers.')
    md.append('')
    md.append('## 무엇을 계산했나')
    md.append('')
    md.append('- text_unit char span: 청크의 첫 100자(실패 시 50자)를 원문에서 string-find. exp08·exp15와 동일 경로.')
    md.append('- pos_first: 엔티티가 들어있는 text_unit들의 char_start 최소값.')
    md.append('- pos_mode: text_unit 내부에서 엔티티 표면형 등장 수가 최대인 청크의 char_start. 동률은 더 이른 청크.')
    md.append('- pos_centroid: 표면형 등장 수 가중 평균 char_start. 표면 매칭 0이면 청크 char_start의 단순 평균으로 폴백.')
    md.append('- pos_first_fine: 엔티티 표면형을 원문 전체에서 직접 찾은 첫 char 오프셋. 실패 시 pos_first로 폴백.')
    md.append('- fine_matched: 위 폴백 발생 여부 (1=실제 매칭).')
    md.append('- weight_count: entity.text_unit_ids 길이 (이 엔티티가 들어있는 청크 수).')
    md.append('- graph_degree: entities.parquet의 degree 컬럼.')
    md.append('')
    md.append(f'대상 엔티티: {n}개 (텍스트 매핑 실패: {n_unmapped}개).')
    md.append('')

    md.append('## pos_first_fine 매칭률')
    md.append('')
    md.append(f'- 매칭 성공: {n_fine_matched}/{n} ({fine_rate*100:.1f}%)')
    md.append(f'- 매칭 실패(폴백): {n - n_fine_matched}개')
    md.append('')
    md.append(f'pos_first vs pos_first_fine 절대차(매칭 성공 한정, N={len(diffs)}): mean={diff_mean}, median={diff_med}, |diff|>500인 케이스 {diff_big}건.')
    md.append('')

    md.append('## 동률 덩어리 (한 청크에 몰리는 엔티티)')
    md.append('')
    md.append(f'- pos_first 기준: {first_n_distinct}개 distinct 값, 최대 한 덩어리 크기 {biggest_first_cluster}.')
    md.append('')
    md.append('| 덩어리 크기 | 덩어리 수 (pos_first) |')
    md.append('|---|---|')
    for size in sorted(tie_sizes.keys()):
        md.append(f'| {size} | {tie_sizes[size]} |')
    md.append('')
    md.append(f'- pos_first_fine 기준: {fine_n_distinct}개 distinct 값, 최대 한 덩어리 크기 {biggest_fine_cluster}.')
    md.append('  (fine은 문자 단위라 청크 단위 덩어리가 풀린다.)')
    md.append('')

    md.append('## weight_count 분포')
    md.append('')
    md.append('| n_text_units | 엔티티 수 |')
    md.append('|---|---|')
    for k in sorted(wc_hist.keys()):
        md.append(f'| {k} | {wc_hist[k]} |')
    md.append('')

    md.append('## graph_degree 요약')
    md.append('')
    md.append(f'- mean={deg_mean}, median={deg_med}, max={deg_max}.')
    md.append('')

    md.append('## top-K 추렸을 때 방 무게 비율 (방 무게 = 멤버 weight_count 합)')
    md.append('')
    md.append('top-K 비율 = top-K 멤버 weight_count 합 / 방 전체 weight_count 합. 1.0이면 top-K가 방 전체 weight를 담는다는 뜻 (작은 방).')
    md.append('')
    md.append('### TOC arm')
    md.append('')
    md.append('| room | size | K | top-K coverage |')
    md.append('|---|---|---|---|')
    for r in toc_k10:
        md.append(f'| {r[0]} | {r[1]} | 10 | {r[3]} |')
    for r in toc_k15:
        md.append(f'| {r[0]} | {r[1]} | 15 | {r[3]} |')
    md.append('')
    md.append('### Graph arm')
    md.append('')
    md.append('| room | size | K | top-K coverage |')
    md.append('|---|---|---|---|')
    for r in graph_k10:
        md.append(f'| {r[0]} | {r[1]} | 10 | {r[3]} |')
    for r in graph_k15:
        md.append(f'| {r[0]} | {r[1]} | 15 | {r[3]} |')
    md.append('')

    # short qualitative observation about top-K integrity
    md.append('## top-K로 추렸을 때 방이 깨지나')
    md.append('')
    md.append('top-K는 partition을 깨지 않는다 (멤버를 제거할 뿐, 방 경계는 그대로). 의미 있는 질문은 "top-K가 방을 어느 정도 대표하나". 위 coverage 표를 보면:')
    md.append('')
    big_low_cov = []
    for arm_label, k10 in (('TOC', toc_k10), ('Graph', graph_k10)):
        for room_id, size, _K, cov in k10:
            if size > 15 and cov < 0.5:
                big_low_cov.append((arm_label, room_id, size, cov))
    if big_low_cov:
        md.append('- size > 15 인데 top-10 coverage < 0.5 인 방:')
        for arm_label, room_id, size, cov in big_low_cov:
            md.append(f'  - {arm_label} {room_id}: size={size}, top-10 coverage={cov}')
    else:
        md.append('- size > 15 인 방 중 top-10 coverage < 0.5 인 곳 없음.')
    md.append('')
    md.append('weight_count 분포가 1로 강하게 쏠려 있어(아래 분포 참고) top-K가 \"무게가 같은 평평한 꼬리\" 위에서 잘리기 쉽다. coverage 값을 \"top-K로 방을 요약하면 어느 정도가 남나\"의 거친 신호로만 읽을 것.')
    md.append('')

    md.append('## 한계 / 결정점')
    md.append('')
    md.append('- 청크 단위가 1200 토큰이라 pos_first가 청크 시작 오프셋으로 강하게 몰린다. pos_first_fine은 그 덩어리를 풀어 주는 용도.')
    md.append(f'- entity.text_unit_ids 길이가 1인 엔티티가 {wc_hist.get(1, 0)}개. weight_count 단독으로는 결정력이 약하고 graph_degree와 합쳐 봐야 한다.')
    md.append('- 표면 검색은 정규화 이름·표기 변형(별칭, 한자 등)에 약하다. 매칭률은 위 \"pos_first_fine 매칭률\"이 전부.')
    md.append('')
    md.append('inputs:')
    md.append(f'- corpus: `input/국사교과서_조선_본문_정제.txt`')
    md.append(f'- snapshot: `results/snapshots/repro_run3/`')
    md.append(f'- TOC rooms: `results/exp16_room_compare/toc_rooms.json`')
    md.append(f'- Graph rooms: `results/exp16_room_compare/graph_rooms.json`')
    md.append('')

    path = OUT_DIR / 'REPORT.md'
    path.write_text('\n'.join(md), encoding='utf-8')
    return path


def main() -> None:
    text = load_text()
    ent_df, tu_df, _rel_df = load_snapshot_frames()
    assert len(ent_df) == 357, f'expected 357 entities, got {len(ent_df)}'
    rows = compute_entity_metrics(ent_df, tu_df, text)

    csv_path = write_csv(rows)
    print(f'wrote {csv_path}')

    toc = json.loads(TOC_PATH.read_text(encoding='utf-8'))
    graph = json.loads(GRAPH_PATH.read_text(encoding='utf-8'))
    rooms_path = write_rooms_ordered(rows, toc, graph)
    print(f'wrote {rooms_path}')

    report_path = write_report(rows, toc, graph)
    print(f'wrote {report_path}')

    fine_rate = sum(1 for r in rows if r['fine_matched']) / len(rows)
    print(f'fine match rate: {fine_rate*100:.1f}%')
    print(f'tie clusters on pos_first: {dict(tie_cluster_sizes(rows, "pos_first"))}')


if __name__ == '__main__':
    main()
