"""Render one or two palace json files into a single self-contained html
for 2D room/node review and presentation preview.

Usage:
    python results/viewer/build_viewer.py \\
        --toc   results/rooms/repro_run3_K6_toc.palace.json \\
        --graph results/rooms/repro_run3_K10_embedding.palace.json \\
        --out   results/viewer/room_preview.html

At least one arm file must exist. The output is a single html with all
CSS and data inlined; no external CDN, fonts, or libraries. Double-click
the file to open it in any modern browser.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TOC = REPO / 'results' / 'rooms' / 'repro_run3_K6_toc.palace.json'
DEFAULT_GRAPH = REPO / 'results' / 'rooms' / 'repro_run3_K10_embedding.palace.json'
DEFAULT_OUT = REPO / 'results' / 'viewer' / 'room_preview.html'


def load_palace(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def summarize_arm(palace: dict) -> dict:
    rooms = palace.get('rooms', [])
    kept_total = 0
    demoted_total = 0
    empty_rooms = 0
    for r in rooms:
        kept = r.get('kept', []) or []
        demoted = r.get('demoted', []) or []
        kept_total += len(kept)
        demoted_total += len(demoted)
        if not kept:
            empty_rooms += 1
    p = palace.get('palace', {}) or {}
    pipeline = p.get('pipeline') or {}
    source = p.get('source') or {}
    return {
        'title': p.get('title') or palace.get('id') or '(no title)',
        'k': pipeline.get('k'),
        'merge': pipeline.get('merge'),
        'llm_model': pipeline.get('llm_model'),
        'entity_count': source.get('entity_count'),
        'room_count': p.get('room_count', len(rooms)),
        'kept_total': kept_total,
        'demoted_total': demoted_total,
        'empty_rooms': empty_rooms,
    }


CSS = """
:root {
    --bg: #fafafa;
    --fg: #1a1a1a;
    --muted: #6b6b6b;
    --card-bg: #ffffff;
    --card-border: #e5e5e5;
    --tag-bg: #f1f1f3;
    --tag-fg: #1a1a1a;
    --tag-border: transparent;
    --tag-fallback-fg: #8a8a8a;
    --tag-fallback-border: #c8c8c8;
    --tag-demote-bg: #f6f6f6;
    --tag-demote-fg: #8a8a8a;
    --accent: #1e6fff;
    --accent-fg: #ffffff;
    --button-bg: #ffffff;
    --button-border: #d0d0d0;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #18181a;
        --fg: #f0f0f2;
        --muted: #9a9a9e;
        --card-bg: #232326;
        --card-border: #34343a;
        --tag-bg: #2e2e33;
        --tag-fg: #f0f0f2;
        --tag-border: transparent;
        --tag-fallback-fg: #9a9a9e;
        --tag-fallback-border: #4a4a52;
        --tag-demote-bg: #2a2a2e;
        --tag-demote-fg: #8a8a8e;
        --accent: #5b95ff;
        --accent-fg: #0a0a0c;
        --button-bg: #232326;
        --button-border: #44444c;
    }
}
* { box-sizing: border-box; }
html, body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
        "Noto Sans KR", Helvetica, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.45;
}
header.top {
    padding: 18px 24px 14px;
    border-bottom: 0.5px solid var(--card-border);
    background: var(--card-bg);
}
header.top h1 {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 6px 0;
}
.meta-row {
    color: var(--muted);
    font-size: 12.5px;
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
}
.meta-row span b {
    color: var(--fg);
    font-weight: 600;
}
.toolbar {
    padding: 12px 24px;
    display: flex;
    gap: 8px;
    align-items: center;
    border-bottom: 0.5px solid var(--card-border);
    background: var(--card-bg);
}
.toolbar .arm-btn {
    appearance: none;
    border: 0.5px solid var(--button-border);
    background: var(--button-bg);
    color: var(--fg);
    padding: 6px 14px;
    border-radius: 999px;
    font: inherit;
    cursor: pointer;
}
.toolbar .arm-btn[aria-pressed="true"] {
    background: var(--accent);
    color: var(--accent-fg);
    border-color: var(--accent);
}
.toolbar .arm-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.toolbar .arm-summary {
    margin-left: auto;
    color: var(--muted);
    font-size: 12.5px;
}
main {
    padding: 16px 24px 80px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px;
}
article.room {
    background: var(--card-bg);
    border: 0.5px solid var(--card-border);
    border-radius: 12px;
    padding: 14px 14px 10px;
    display: flex;
    flex-direction: column;
    min-height: 120px;
}
article.room > header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 10px;
    gap: 10px;
}
article.room > header h3 {
    margin: 0;
    font-size: 14.5px;
    font-weight: 600;
    line-height: 1.3;
}
article.room > header .kept-count {
    color: var(--muted);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
ul.tags {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
ul.tags li.tag {
    background: var(--tag-bg);
    color: var(--tag-fg);
    border: 0.5px solid var(--tag-border);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 12.5px;
    max-width: 100%;
    white-space: normal;
    word-break: keep-all;
}
ul.tags li.tag.top {
    font-weight: 700;
}
ul.tags li.tag.top::before {
    content: "\\2022";
    display: inline-block;
    margin-right: 4px;
    color: var(--accent);
}
ul.tags li.tag.fallback {
    color: var(--tag-fallback-fg);
    border: 1px dashed var(--tag-fallback-border);
    background: transparent;
}
.empty-note {
    color: var(--muted);
    font-size: 12.5px;
    font-style: italic;
}
details.demoted {
    margin-top: 12px;
    border-top: 0.5px dashed var(--card-border);
    padding-top: 8px;
    color: var(--muted);
}
details.demoted summary {
    cursor: pointer;
    font-size: 12px;
    color: var(--muted);
    list-style: none;
    user-select: none;
}
details.demoted summary::-webkit-details-marker { display: none; }
details.demoted summary::before {
    content: "\\25B8";
    display: inline-block;
    width: 12px;
    transition: transform 120ms ease;
}
details.demoted[open] summary::before { content: "\\25BE"; }
details.demoted ul.tags { margin-top: 8px; }
details.demoted ul.tags li.tag {
    background: var(--tag-demote-bg);
    color: var(--tag-demote-fg);
}
footer.legend {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 8px 24px;
    background: var(--card-bg);
    border-top: 0.5px solid var(--card-border);
    font-size: 12px;
    color: var(--muted);
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
}
footer.legend .swatch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
footer.legend .sw {
    display: inline-block;
    width: 16px;
    height: 12px;
    border-radius: 4px;
    background: var(--tag-bg);
    border: 0.5px solid var(--tag-border);
}
footer.legend .sw.top {
    background: var(--tag-bg);
}
footer.legend .sw.top::before {
    content: "\\2022";
    color: var(--accent);
    font-weight: 700;
    display: inline-block;
    width: 100%;
    text-align: center;
    line-height: 12px;
}
footer.legend .sw.fb {
    background: transparent;
    border: 1px dashed var(--tag-fallback-border);
}
footer.legend .sw.demote {
    background: var(--tag-demote-bg);
}
"""


JS = r"""
const DATA = JSON.parse(document.getElementById('palace-data').textContent);

function fmt(n) {
    if (n === null || n === undefined) return '-';
    return Number.isInteger(n) ? String(n) : String(n);
}

function escapeAttr(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function tagOf(item, isDemoted) {
    const cls = ['tag'];
    if (!isDemoted && item.rank === 1) cls.push('top');
    if (!isDemoted && item.order_confidence === 'fallback') cls.push('fallback');
    const li = document.createElement('li');
    li.className = cls.join(' ');
    li.textContent = item.title || '(no title)';
    if (item.caption) li.title = item.caption;
    else if (item.description) li.title = item.description;
    return li;
}

function renderArm(armKey) {
    const arm = DATA.arms[armKey];
    const main = document.getElementById('rooms');
    main.innerHTML = '';
    if (!arm) return;
    const armSummary = document.getElementById('arm-summary');
    const s = arm.summary;
    armSummary.textContent =
        'rooms ' + fmt(s.room_count) + ' · kept ' + fmt(s.kept_total)
        + ' · demote ' + fmt(s.demoted_total)
        + ' · empty ' + fmt(s.empty_rooms);

    const rooms = arm.palace.rooms || [];
    rooms.forEach((room, idx) => {
        const art = document.createElement('article');
        art.className = 'room';
        const head = document.createElement('header');
        const h3 = document.createElement('h3');
        h3.textContent = (idx + 1) + '. ' + (room.name || '(unnamed)');
        head.appendChild(h3);
        const count = document.createElement('span');
        count.className = 'kept-count';
        const keptN = (room.kept || []).length;
        count.textContent = 'kept ' + keptN;
        head.appendChild(count);
        art.appendChild(head);

        if (keptN === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-note';
            empty.textContent = '노드 없음 · 흡수됨';
            art.appendChild(empty);
        } else {
            const ul = document.createElement('ul');
            ul.className = 'tags';
            (room.kept || []).forEach(item => ul.appendChild(tagOf(item, false)));
            art.appendChild(ul);
        }

        const demoted = room.demoted || [];
        if (demoted.length > 0) {
            const det = document.createElement('details');
            det.className = 'demoted';
            const sum = document.createElement('summary');
            sum.textContent = ' 숨김 (demote) ' + demoted.length;
            det.appendChild(sum);
            const dUl = document.createElement('ul');
            dUl.className = 'tags';
            demoted.forEach(item => dUl.appendChild(tagOf(item, true)));
            det.appendChild(dUl);
            art.appendChild(det);
        }

        main.appendChild(art);
    });
}

function setArm(armKey) {
    if (!DATA.arms[armKey]) return;
    document.querySelectorAll('.arm-btn').forEach(b => {
        b.setAttribute('aria-pressed', b.dataset.arm === armKey ? 'true' : 'false');
    });
    const armMeta = DATA.arms[armKey].summary;
    const meta = document.getElementById('palace-meta');
    meta.innerHTML = '';
    function addSpan(label, value) {
        const s = document.createElement('span');
        const b = document.createElement('b');
        b.textContent = label;
        s.appendChild(b);
        s.appendChild(document.createTextNode(' ' + (value === null || value === undefined ? '-' : value)));
        meta.appendChild(s);
    }
    addSpan('k', armMeta.k);
    addSpan('merge', armMeta.merge);
    addSpan('llm', armMeta.llm_model);
    addSpan('entities', armMeta.entity_count);
    addSpan('rooms', armMeta.room_count);
    document.getElementById('palace-title').textContent = armMeta.title;
    renderArm(armKey);
}

document.querySelectorAll('.arm-btn').forEach(b => {
    if (!DATA.arms[b.dataset.arm]) {
        b.disabled = true;
        return;
    }
    b.addEventListener('click', () => setArm(b.dataset.arm));
});

const initial = DATA.arms.toc ? 'toc' : 'graph';
setArm(initial);
"""


def build_html(arms: dict, source_paths: dict) -> str:
    payload = {
        'arms': {
            k: {
                'palace': v['palace_doc'],
                'summary': v['summary'],
                'source_path': v['source_rel'],
            }
            for k, v in arms.items()
        },
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    # Avoid breaking out of the embedded script tag.
    data_json = data_json.replace('</', '<\\/')

    toc_present = 'toc' in arms
    graph_present = 'graph' in arms

    def btn(arm_key: str, label: str, present: bool) -> str:
        disabled = '' if present else ' disabled'
        return (
            f'<button class="arm-btn" type="button" data-arm="{arm_key}"'
            f' aria-pressed="false"{disabled}>{label}</button>'
        )

    head_title = 'Room preview'
    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{head_title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{CSS}
</style>
</head>
<body>
<header class="top">
    <h1 id="palace-title">Room preview</h1>
    <div class="meta-row" id="palace-meta"></div>
</header>
<nav class="toolbar">
    {btn('toc', 'TOC arm', toc_present)}
    {btn('graph', 'GRAPH arm', graph_present)}
    <span class="arm-summary" id="arm-summary"></span>
</nav>
<main id="rooms"></main>
<footer class="legend">
    <span class="swatch"><span class="sw top"></span> rank 1 (강조)</span>
    <span class="swatch"><span class="sw"></span> keep</span>
    <span class="swatch"><span class="sw fb"></span> 순서 불확실 (fallback)</span>
    <span class="swatch"><span class="sw demote"></span> 숨김 (demote)</span>
</footer>
<script id="palace-data" type="application/json">
{data_json}
</script>
<script>
{JS}
</script>
</body>
</html>
"""
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--toc', default=str(DEFAULT_TOC),
                    help='TOC arm palace json (default: %(default)s)')
    ap.add_argument('--graph', default=str(DEFAULT_GRAPH),
                    help='GRAPH arm palace json (default: %(default)s)')
    ap.add_argument('--out', default=str(DEFAULT_OUT),
                    help='output html (default: %(default)s)')
    args = ap.parse_args()

    paths = {'toc': Path(args.toc), 'graph': Path(args.graph)}
    arms: dict[str, dict] = {}
    missing: list[tuple[str, Path]] = []
    for key, path in paths.items():
        if path.exists():
            try:
                doc = load_palace(path)
            except (json.JSONDecodeError, OSError) as e:
                print(f'STOP: failed to read {key} palace at {path}: {e}')
                sys.exit(2)
            try:
                source_rel = str(path.relative_to(REPO)).replace('\\', '/')
            except ValueError:
                source_rel = str(path)
            arms[key] = {
                'palace_doc': doc,
                'summary': summarize_arm(doc),
                'source_rel': source_rel,
            }
        else:
            missing.append((key, path))

    if not arms:
        print('STOP: no palace json found for either arm. Missing:')
        for key, path in missing:
            try:
                rel = str(path.relative_to(REPO)).replace('\\', '/')
            except ValueError:
                rel = str(path)
            print(f'  - {key}: {rel}')
        sys.exit(2)

    for key, path in missing:
        try:
            rel = str(path.relative_to(REPO)).replace('\\', '/')
        except ValueError:
            rel = str(path)
        print(f'note: {key} arm missing ({rel}); skipping that toggle')

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(arms, paths)
    out_path.write_text(html, encoding='utf-8')

    try:
        out_rel = str(out_path.relative_to(REPO)).replace('\\', '/')
    except ValueError:
        out_rel = str(out_path)
    print(f'wrote: {out_rel}')
    for key, info in arms.items():
        s = info['summary']
        print(
            f'  {key}: rooms={s["room_count"]} kept={s["kept_total"]} '
            f'demote={s["demoted_total"]} empty={s["empty_rooms"]} '
            f'(source: {info["source_rel"]})'
        )


if __name__ == '__main__':
    main()
