"""Populate image_match_accuracy_v3*.html DATA (and optional DIFF) blocks.

Canonical values (score / tier / node / basis / cap_title / page / png path)
come from the source `*_image_match_accuracy_*.md` so the HTML matches the md
exactly. We then re-run matching once to capture the pre-collision target for
`미배치 (충돌)` rows (the md hides which node they almost won). Room name comes
from the source `.palace.json` via the matched node.

Each figure PNG is inlined as base64 data URI, resized to 400px long edge via
Pillow so the single-file HTML stays manageable. Only the `const DATA = [...]`
block between DATA_START and DATA_END markers is rewritten; with --diff-vs-md
the `const DIFF = [...]` block between DIFF_START and DIFF_END is also rewritten.

Default invocation populates cleaned-data v3 into image_match_accuracy_v3.html.
For raw: pass --source-md, --captions, --diff-vs-md, --target-html.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path

import lancedb
import numpy as np
import pandas as pd
from PIL import Image

from palace import match_images as mi


DEFAULT_SOURCE_MD = (
    mi.REPO / 'results' / 'audit' / '2026-06-11_image_match_accuracy_v3.md'
)
DEFAULT_TARGET_HTML = (
    mi.REPO / 'results' / 'audit' / 'image_match_accuracy_v3.html'
)


def main() -> int:
    mi._load_dotenv(mi.REPO / '.env')

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-md', default=str(DEFAULT_SOURCE_MD),
                    help='audit md to pull canonical scores/tiers/nodes from')
    ap.add_argument('--captions', default=str(mi.DEFAULT_CAPTIONS),
                    help='figcaption md (must match the run that produced --source-md)')
    ap.add_argument('--diff-vs-md', default=None,
                    help='optional second md to diff against (renders DIFF block)')
    ap.add_argument('--target-html', default=str(DEFAULT_TARGET_HTML),
                    help='HTML file to populate (modified in place)')
    args = ap.parse_args()

    palace_path = mi.DEFAULT_PALACE
    snapshot = mi.DEFAULT_SNAPSHOT
    fig_dir = mi.DEFAULT_FIG_DIR
    cap_path = Path(args.captions).resolve()
    pagesplit = mi.DEFAULT_PAGESPLIT
    html_path = Path(args.target_html).resolve()
    source_md_path = Path(args.source_md).resolve()
    diff_md_path = Path(args.diff_vs_md).resolve() if args.diff_vs_md else None

    if not source_md_path.exists():
        raise SystemExit(f'STOP: source md not found: {source_md_path}')
    md_rows = mi._parse_prev_md(source_md_path)
    if not md_rows:
        raise SystemExit(f'STOP: source md parsed 0 rows from {source_md_path}')
    diff_rows = mi._parse_prev_md(diff_md_path) if diff_md_path else None
    if diff_md_path and not diff_rows:
        raise SystemExit(f'STOP: --diff-vs-md parsed 0 rows from {diff_md_path}')

    nodes = mi.load_palace_nodes(palace_path)
    titles = sorted(nodes.keys())

    ents_df = pd.read_parquet(snapshot / 'entities.parquet')
    title_to_id = dict(zip(ents_df['title'], ents_df['id']))
    title_to_degree = {
        t: int(d) for t, d in zip(ents_df['title'], ents_df['degree'])
    }
    max_degree = int(ents_df['degree'].max())

    db = lancedb.connect(str(snapshot / 'lancedb'))
    desc = db.open_table('entity_description').to_pandas()
    id_to_vec = {
        r['id']: np.array(r['vector'], dtype=np.float64)
        for _, r in desc.iterrows()
    }
    title_vecs = {
        t: id_to_vec[title_to_id[t]]
        for t in titles
        if t in title_to_id and title_to_id[t] in id_to_vec
    }

    pages = mi.build_page_bodies(pagesplit)
    title_pages = mi.build_entity_pages(titles, pages)

    raw_captions = mi.parse_captions(cap_path)
    pngs = mi.list_pngs(fig_dir)
    if len(raw_captions) != len(pngs):
        raise SystemExit(
            f'STOP: caption count {len(raw_captions)} != png count {len(pngs)}'
        )

    rows: list[dict] = []
    for cap, (png_path, page, idx) in zip(raw_captions, pngs):
        for cap_title, cap_full in mi.detect_joined_caption(cap):
            rows.append({
                'png': png_path,
                'page': page,
                'idx': idx,
                'cap_title': cap_title,
                'caption': cap_full,
            })

    unique_caps = sorted({r['caption'] for r in rows})
    vecs = mi.embed_captions(unique_caps)
    cap_to_vec = {t: vecs[i] for i, t in enumerate(unique_caps)}

    for r in rows:
        cap_vec = cap_to_vec[r['caption']]
        cap_tokens = mi.tokenize_caption(r['cap_title'])
        win = {r['page'] + d for d in range(-mi.PAGE_WINDOW, mi.PAGE_WINDOW + 1)}
        cand_1st = [
            t for t in titles
            if title_pages.get(t) and (title_pages[t] & win)
        ]
        bt, bs, bm = (None, -1e9, {})
        if cand_1st:
            bt, bs, bm = mi.best_in(
                cand_1st, cap_tokens, cap_vec,
                title_vecs, title_to_degree, max_degree,
            )
        if bt is not None and bs >= mi.THRESHOLD_LOCAL:
            r['tier'] = '1차'
            r['match'] = bt
            r['score'] = bs
            r['meta'] = bm
            continue
        bt2, bs2, bm2 = mi.best_in(
            titles, cap_tokens, cap_vec,
            title_vecs, title_to_degree, max_degree,
        )
        if bt2 is not None and bs2 >= mi.THRESHOLD_CASCADE:
            r['tier'] = '캐스케이드'
            r['match'] = bt2
            r['score'] = bs2
            r['meta'] = bm2
        else:
            r['tier'] = '미배치'
            r['match'] = None
            r['score'] = bs2 if bt2 is not None else bs
            r['meta'] = bm2 if bt2 is not None else bm

    # snapshot pre-collision target before resolution
    for r in rows:
        r['pre_match'] = r['match']

    by_node: dict[str, list[dict]] = {}
    for r in rows:
        if r['match']:
            by_node.setdefault(r['match'], []).append(r)
    for node, lst in by_node.items():
        if len(lst) <= 1:
            continue
        lst.sort(key=lambda x: x['score'], reverse=True)
        winner = lst[0]
        for loser in lst[1:]:
            loser['tier'] = '미배치 (충돌)'
            loser['lost_node'] = node
            loser['lost_to_title'] = winner['cap_title']
            loser['match'] = None

    palace_data = json.loads(palace_path.read_text(encoding='utf-8'))
    node_to_room: dict[str, str] = {}
    for room in palace_data['rooms']:
        for bucket in ('kept', 'demoted'):
            for ent in room.get(bucket, []):
                node_to_room[ent['title']] = room['name']

    def png_to_data_uri(p: Path, max_edge: int = 400) -> str:
        im = Image.open(p)
        if im.mode == 'P':
            im = im.convert('RGBA')
        w, h = im.size
        if max(w, h) > max_edge:
            ratio = max_edge / float(max(w, h))
            im = im.resize(
                (max(1, int(w * ratio)), max(1, int(h * ratio))),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        im.save(buf, format='PNG', optimize=True)
        return 'data:image/png;base64,' + base64.b64encode(
            buf.getvalue()
        ).decode('ascii')

    img_cache: dict[Path, str] = {}
    def img_for(p: Path) -> str:
        if p not in img_cache:
            img_cache[p] = png_to_data_uri(p)
        return img_cache[p]

    def jstr(s) -> str:
        return json.dumps(s, ensure_ascii=False)

    if len(md_rows) != len(rows):
        raise SystemExit(
            f'STOP: md row count {len(md_rows)} != fresh row count {len(rows)}'
        )

    entries: list[str] = []
    placed_n = 0
    gallery_n = 0
    for i, r in enumerate(rows, 1):
        md = md_rows[i]
        if md['cap_title'] != r['cap_title']:
            raise SystemExit(
                f'STOP: row {i} cap_title mismatch '
                f'md={md["cap_title"]!r} fresh={r["cap_title"]!r}'
            )
        img = img_for(r['png'])
        score = md['score']
        tier = md['tier']
        match_node = md['match']
        basis = '이름' if 'name+' in md['signal'] else '임베딩'

        if match_node:
            placed_n += 1
            room = node_to_room.get(match_node)
            room_js = jstr(room) if room else 'null'
            entries.append(
                '  { '
                f'img:{jstr(img)}, '
                f'title:{jstr(r["cap_title"])}, '
                f'status:"placed", '
                f'node:{jstr(match_node)}, '
                f'room:{room_js}, '
                f'tier:{jstr(tier)}, '
                f'basis:{jstr(basis)}, '
                f'score:{score}'
                ' }'
            )
        else:
            gallery_n += 1
            if tier == '미배치 (충돌)':
                reason = '충돌'
                note = (
                    f'노드 \'{r.get("lost_node", "?")}\'에 '
                    f'\'{r.get("lost_to_title", "?")}\'이(가) 먼저 배치됨'
                )
            else:
                reason = '엔티티 없음'
                note = f'추출 범위 밖 (\'{r["cap_title"]}\' 노드 없음)'
            parts = [
                f'img:{jstr(img)}',
                f'title:{jstr(r["cap_title"])}',
                f'status:"gallery"',
                f'reason:{jstr(reason)}',
                f'reasonNote:{jstr(note)}',
            ]
            if score > 0:
                parts.append(f'score:{score}')
            entries.append('  { ' + ', '.join(parts) + ' }')

    data_block = 'const DATA = [\n' + ',\n'.join(entries) + ',\n];'

    # diff entries (optional)
    def _ba(row: dict) -> str:
        node = row['match'] or '-'
        return f'{node} · {row["tier"]} · {row["score"]:.3f}'

    diff_entries: list[str] = []
    if diff_rows is not None:
        for i, r in enumerate(rows, 1):
            src = md_rows[i]
            other = diff_rows.get(i)
            if not other:
                continue
            same = (
                (src['match'] or '-') == (other['match'] or '-')
                and src['tier'] == other['tier']
            )
            if same:
                continue
            diff_entries.append(
                '  { '
                f'row:{i}, '
                f'img:{jstr(img_for(r["png"]))}, '
                f'title:{jstr(src["cap_title"])}, '
                f'before:{jstr(_ba(other))}, '
                f'after:{jstr(_ba(src))}'
                ' }'
            )

    html = html_path.read_text(encoding='utf-8')
    start_re = re.compile(r'^const DATA = \[', re.M)
    m = start_re.search(html)
    if not m:
        raise SystemExit('STOP: DATA start marker not found in HTML')
    data_end_pos = html.find('/* DATA_END */', m.start())
    if data_end_pos < 0:
        raise SystemExit('STOP: /* DATA_END */ not found after DATA start')
    last_close = html.rfind('];', m.start(), data_end_pos)
    if last_close < 0:
        raise SystemExit('STOP: closing `];` not found between markers')
    end_pos = last_close + len('];')
    new_html = html[: m.start()] + data_block + html[end_pos:]

    if diff_rows is not None:
        diff_block = (
            'const DIFF = [\n' + ',\n'.join(diff_entries) + ',\n];'
            if diff_entries
            else 'const DIFF = [];'
        )
        diff_start_re = re.compile(r'^const DIFF = \[', re.M)
        m2 = diff_start_re.search(new_html)
        if not m2:
            raise SystemExit('STOP: DIFF start marker not found in HTML '
                             '(--target-html missing DIFF block?)')
        diff_end_pos = new_html.find('/* DIFF_END */', m2.start())
        if diff_end_pos < 0:
            raise SystemExit('STOP: /* DIFF_END */ not found after DIFF start')
        last_close2 = new_html.rfind('];', m2.start(), diff_end_pos)
        if last_close2 < 0:
            raise SystemExit('STOP: closing `];` not found in DIFF block')
        end_pos2 = last_close2 + len('];')
        new_html = new_html[: m2.start()] + diff_block + new_html[end_pos2:]

    html_path.write_text(new_html, encoding='utf-8')

    print(
        f'wrote: {html_path.relative_to(mi.REPO).as_posix()}'
        f' (entries={len(entries)} placed={placed_n} gallery={gallery_n}'
        + (f' diff={len(diff_entries)}' if diff_rows is not None else '')
        + ')'
    )
    print(f'file size: {len(new_html):,} chars')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
