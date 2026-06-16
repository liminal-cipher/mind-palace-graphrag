"""Match figure captions to palace entity nodes for accuracy review.

Pairing assumption: captions in `extracted_figures.md` (document order) align 1:1
with PNGs in `input/img_국사/` sorted by (page, idx) parsed from `fig_{p}_{i}.png`.

Output: console table + `docs/audit/<DATE>_image_match_accuracy.md`.
No `.palace.json` write here; accuracy first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import lancedb
import numpy as np
import pandas as pd

from palace.node_metrics import _surface_variants

# Tunables -----------------------------------------------------------------
THRESHOLD_LOCAL = 0.45    # 1st pass (page-windowed candidates)
THRESHOLD_CASCADE = 0.55  # full-pool cascade (no page constraint -> stricter bar)
NAME_MATCH_BONUS = 0.50
HUB_PENALTY_MAX = 0.10
PAGE_WINDOW = 1
MIN_NAME_LEN = 2  # exclude length-1 entity titles / caption tokens from name-match
OUT_TAG = 'v3'   # appended to audit md filename to avoid overwriting prior run
PREV_TAG = 'v2'  # used to locate prior run for diff section ('' = v1, no suffix)
EMBED_DEPLOYMENT = 'text-embedding-3-small'
API_VERSION = '2024-12-01-preview'

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PALACE = REPO / 'deliverables' / 'korean_history' / 'palace.json'
DEFAULT_SNAPSHOT = REPO / 'snapshots' / 'repro_run3'
DEFAULT_FIG_DIR = REPO / 'input' / 'korean_history' / 'img'
DEFAULT_CAPTIONS = REPO / 'input' / 'korean_history' / 'captions.md'
DEFAULT_PAGESPLIT = REPO / 'input' / 'korean_history' / 'pagesplit.txt'
DEFAULT_OUT_DIR = REPO / 'docs' / 'audit'

CAPTION_TAG_RE = re.compile(r'<figcaption>(.*?)</figcaption>', re.DOTALL)
SPLIT_BAR_RE = re.compile(r'\s*[|￨ㅣ]\s*')  # ASCII bar, halfwidth bar, hangul I
PAGE_MARKER_RE = re.compile(r'\[page(\d+)\]\n?')  # preprocessing pipeline_v2 format
FIG_NAME_RE = re.compile(r'fig_(\d+)_(\d+)\.png$')
TRAILING_PAREN_RE = re.compile(r'\s*\([^)]*\)\s*$')


def strip_trailing_paren(title: str) -> str:
    """Drop a single trailing parenthetical annotation from a caption title.

    "왜관도(국립 중앙 박물관 소장)" -> "왜관도"
    "유정(사명대사) 영정" -> "유정(사명대사) 영정"  (paren is mid-string, not trailing)
    """
    return TRAILING_PAREN_RE.sub('', title).strip()


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


def parse_captions(md_path: Path) -> list[str]:
    text = md_path.read_text(encoding='utf-8')
    return [m.group(1).strip() for m in CAPTION_TAG_RE.finditer(text)]


def detect_joined_caption(caption: str) -> list[tuple[str, str]]:
    """Return [(title, caption_for_embedding), ...].

    Title is the first bar-split segment with trailing parenthetical stripped
    (used for name-match tokenization). Embedding side keeps the full caption.

    Detects "titleA | author titleB | author" pattern (3 bar parts where
    last part is short and middle part has a space). Otherwise single entry.
    """
    parts = SPLIT_BAR_RE.split(caption)
    if (
        len(parts) == 3
        and 0 < len(parts[2].strip()) <= 6
        and ' ' in parts[1].strip()
    ):
        author1, _, rest = parts[1].strip().partition(' ')
        cap_a = f'{parts[0].strip()} | {author1}'
        cap_b = f'{rest} | {parts[2].strip()}'
        return [
            (strip_trailing_paren(parts[0].strip()), cap_a),
            (strip_trailing_paren(rest), cap_b),
        ]
    return [(strip_trailing_paren(parts[0].strip()), caption)]


def list_pngs(fig_dir: Path) -> list[tuple[Path, int, int]]:
    items: list[tuple[Path, int, int]] = []
    for p in fig_dir.iterdir():
        m = FIG_NAME_RE.match(p.name)
        if m:
            items.append((p, int(m.group(1)), int(m.group(2))))
    return sorted(items, key=lambda r: (r[1], r[2]))


def load_palace_nodes(palace_path: Path) -> dict[str, dict]:
    data = json.loads(palace_path.read_text(encoding='utf-8'))
    out: dict[str, dict] = {}
    for room in data['rooms']:
        for bucket in ('kept', 'demoted'):
            for ent in room.get(bucket, []):
                t = ent['title']
                if t in out:
                    continue
                out[t] = {
                    'description': ent.get('description') or '',
                    'kept_or_demoted': bucket,
                    'room_id': room['id'],
                }
    return out


def build_page_bodies(pagesplit_path: Path) -> dict[int, str]:
    text = pagesplit_path.read_text(encoding='utf-8')
    parts = PAGE_MARKER_RE.split(text)
    pages: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        pages[int(parts[i])] = parts[i + 1]
    return pages


def build_entity_pages(
    titles: list[str], pages: dict[int, str]
) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for title in titles:
        variants = _surface_variants(title)
        hits: set[int] = set()
        for p_num, body in pages.items():
            if any(v in body for v in variants):
                hits.add(p_num)
        out[title] = hits
    return out


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def tokenize_caption(text: str) -> list[str]:
    """Whitespace tokenizer for Korean captions.

    No 조사 stripping; caller pairs this with prefix matching so trailing
    particles ride along (e.g., caption token '호패법을' still triggers a
    prefix hit against entity '호패법'). Swap this function per domain.
    """
    return [t for t in text.split() if t]


def name_match_prefix(ent_title: str, cap_tokens: list[str]) -> bool:
    """Match if any surface variant of ent_title equals, prefixes, or is
    prefixed-by any caption token. Both sides must be >= MIN_NAME_LEN chars.

    Direction-symmetric: short caption like '호패' still hits longer entity
    '호패법' because '호패' is a prefix of '호패법'. Suffix-only relations
    (e.g., '원' vs '서원') do not trigger.
    """
    variants = [v for v in _surface_variants(ent_title) if len(v) >= MIN_NAME_LEN]
    if not variants:
        return False
    for v in variants:
        for tok in cap_tokens:
            if len(tok) < MIN_NAME_LEN:
                continue
            if v == tok or v.startswith(tok) or tok.startswith(v):
                return True
    return False


def embed_captions(captions: list[str]) -> np.ndarray:
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=os.environ['GRAPHRAG_API_KEY'],
        api_version=API_VERSION,
        azure_endpoint=os.environ['GRAPHRAG_API_BASE'],
    )
    res = client.embeddings.create(model=EMBED_DEPLOYMENT, input=captions)
    return np.array([d.embedding for d in res.data], dtype=np.float64)


def score_pair(
    cap_tokens: list[str],
    cap_vec: np.ndarray,
    ent_title: str,
    ent_vec: np.ndarray,
    ent_degree: int,
    max_degree: int,
) -> tuple[float, dict]:
    cos = cosine(cap_vec, ent_vec)
    name_match = name_match_prefix(ent_title, cap_tokens)
    bonus = NAME_MATCH_BONUS if name_match else 0.0
    hub_pen = HUB_PENALTY_MAX * (ent_degree / max_degree) if max_degree else 0.0
    return cos + bonus - hub_pen, {
        'cosine': cos,
        'name_match': name_match,
        'hub_pen': hub_pen,
    }


def best_in(
    candidate_titles: list[str],
    cap_tokens: list[str],
    cap_vec: np.ndarray,
    title_vecs: dict[str, np.ndarray],
    title_to_degree: dict[str, int],
    max_degree: int,
) -> tuple[str | None, float, dict]:
    best_t: str | None = None
    best_s = -1e9
    best_m: dict = {}
    for t in candidate_titles:
        if t not in title_vecs:
            continue
        s, meta = score_pair(
            cap_tokens, cap_vec, t, title_vecs[t],
            int(title_to_degree.get(t, 0)), max_degree,
        )
        if s > best_s or (s == best_s and (best_t is None or t < best_t)):
            best_t, best_s, best_m = t, s, meta
    return best_t, best_s, best_m


_PREV_ROW_RE = re.compile(
    r'^\| (\d+) \| (.+?) \| (\d+) \| `(.+?)` \| (.+?) \| (.+?) \| '
    r'([0-9.\-]+) \| (.+?) \|$'
)


def _parse_prev_md(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        m = _PREV_ROW_RE.match(line)
        if not m:
            continue
        i = int(m.group(1))
        match_str = m.group(5).strip()
        out[i] = {
            'cap_title': m.group(2).strip(),
            'page': int(m.group(3)),
            'png': m.group(4),
            'match': None if match_str == '-' else match_str,
            'tier': m.group(6).strip(),
            'score': float(m.group(7)),
            'signal': m.group(8).strip(),
        }
    return out


def _build_diff_section(prev_md_path: Path, new_rows: list[dict]) -> list[str]:
    prev = _parse_prev_md(prev_md_path)
    if not prev:
        return []
    changed: list[tuple[int, dict, dict]] = []
    for i, r in enumerate(new_rows, 1):
        p = prev.get(i)
        if not p:
            continue
        if (r['match'] or '-') == (p['match'] or '-') and r['tier'] == p['tier']:
            continue
        changed.append((i, p, r))
    if not changed:
        return [
            f'## diff vs {prev_md_path.name}',
            '',
            '(매칭/티어 변화 없음)',
        ]
    lines = [
        f'## diff vs {prev_md_path.name}',
        '',
        f'- 바뀐 행: {len(changed)} / {len(new_rows)}',
        '',
        '| # | 제목 | before (노드, tier, 점수) | after (노드, tier, 점수) |',
        '|---:|---|---|---|',
    ]
    for i, p, r in changed:
        before = (
            f'{p["match"] or "-"} · {p["tier"]} · {p["score"]:.3f}'
        )
        after = (
            f'{r["match"] or "-"} · {r["tier"]} · {r["score"]:.3f}'
        )
        lines.append(f'| {i} | {r["cap_title"]} | {before} | {after} |')
    return lines


def write_palace_copy(
    palace_path: Path,
    rows: list[dict],
    out_dir: Path | None = None,
) -> tuple[Path, Path, dict]:
    """Read original .palace.json, attach `images[]` to matched nodes (kept or
    demoted), write `{stem}_with_images.palace.json` next to the source and a
    parallel `{stem}_unplaced_figures.json` for the gallery pool.

    Page is intentionally not propagated to node images per spec.
    """
    data = json.loads(palace_path.read_text(encoding='utf-8'))

    title_to_images: dict[str, list[dict]] = {}
    for r in rows:
        if not r.get('match'):
            continue
        title_to_images.setdefault(r['match'], []).append({
            'path': f'images/{Path(r["png"]).name}',
            'caption': r['caption'],
            'score': round(r['score'], 3),
        })
    for imgs in title_to_images.values():
        imgs.sort(key=lambda x: x['score'], reverse=True)

    attached_nodes = 0
    attached_figs = 0
    for room in data.get('rooms', []):
        for bucket in ('kept', 'demoted'):
            for ent in room.get(bucket, []):
                imgs = title_to_images.get(ent['title'])
                if imgs:
                    ent['images'] = imgs
                    attached_nodes += 1
                    attached_figs += len(imgs)

    unplaced: list[dict] = []
    for i, r in enumerate(rows, 1):
        if r.get('match'):
            continue
        reason = 'collision' if r['tier'] == '미배치 (충돌)' else 'no_fit'
        unplaced.append({
            'row': i,
            'path': f'images/{Path(r["png"]).name}',
            'page': r['page'],
            'caption_title': r['cap_title'],
            'caption': r['caption'],
            'reason': reason,
            'best_score': round(r['score'], 3),
        })

    data['image_matching'] = {
        'ran_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_palace': palace_path.relative_to(REPO).as_posix(),
        'threshold_local': THRESHOLD_LOCAL,
        'threshold_cascade': THRESHOLD_CASCADE,
        'name_match_bonus': NAME_MATCH_BONUS,
        'hub_penalty_max': HUB_PENALTY_MAX,
        'page_window': PAGE_WINDOW,
        'min_name_len': MIN_NAME_LEN,
        'embed_deployment': EMBED_DEPLOYMENT,
        'caption_rows': len(rows),
        'attached_nodes': attached_nodes,
        'attached_figures': attached_figs,
        'unplaced_figures': len(unplaced),
    }

    # Deliverable is self-contained: palace_with_images.json + unplaced_figures.json
    # sit beside the source palace.json, and every referenced figure (placed or
    # unplaced) is copied into images/ so node paths ('images/<file>') resolve
    # against the same folder the API serves.
    base_dir = out_dir or palace_path.parent
    img_dir = base_dir / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        src = REPO / r['png']
        if src.exists():
            shutil.copy2(src, img_dir / src.name)

    out_palace = base_dir / 'palace_with_images.json'
    out_unplaced = base_dir / 'unplaced_figures.json'
    out_palace.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    out_unplaced.write_text(
        json.dumps(unplaced, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return out_palace, out_unplaced, data['image_matching']


def signal_str(meta: dict) -> str:
    if not meta:
        return '-'
    parts: list[str] = []
    if meta.get('name_match'):
        parts.append(f'name+{NAME_MATCH_BONUS:.2f}')
    parts.append(f'cos={meta["cosine"]:.3f}')
    if meta.get('hub_pen', 0.0) > 0.0:
        parts.append(f'hub-{meta["hub_pen"]:.3f}')
    return ' '.join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--palace', default=str(DEFAULT_PALACE))
    ap.add_argument('--snapshot', default=str(DEFAULT_SNAPSHOT))
    ap.add_argument('--figures-dir', default=str(DEFAULT_FIG_DIR))
    ap.add_argument('--captions', default=str(DEFAULT_CAPTIONS))
    ap.add_argument('--pagesplit', default=str(DEFAULT_PAGESPLIT))
    ap.add_argument('--out-dir', default=str(DEFAULT_OUT_DIR))
    ap.add_argument('--tag', default=OUT_TAG,
                    help='filename suffix for new audit md '
                         '(default: %(default)s)')
    ap.add_argument('--prev-tag', default=PREV_TAG,
                    help="filename suffix for prior audit md to diff against "
                         "('' = no prior, no diff section)")
    ap.add_argument('--write-palace', action='store_true',
                    help='also write `{stem}_with_images.palace.json` and '
                         '`{stem}_unplaced_figures.json` next to the source palace')
    ap.add_argument('--palace-out-dir', default=None,
                    help='override directory for --write-palace outputs '
                         '(default: same dir as --palace)')
    args = ap.parse_args()

    _load_dotenv(REPO / '.env')

    palace_path = Path(args.palace).resolve()
    snapshot = Path(args.snapshot).resolve()
    fig_dir = Path(args.figures_dir).resolve()
    cap_path = Path(args.captions).resolve()
    pagesplit = Path(args.pagesplit).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes = load_palace_nodes(palace_path)
    titles = sorted(nodes.keys())

    ents_df = pd.read_parquet(snapshot / 'entities.parquet')
    title_to_id = dict(zip(ents_df['title'], ents_df['id']))
    title_to_degree = {t: int(d) for t, d in zip(ents_df['title'], ents_df['degree'])}
    max_degree = int(ents_df['degree'].max())

    db = lancedb.connect(str(snapshot / 'lancedb'))
    desc_tab = db.open_table('entity_description').to_pandas()
    id_to_vec = {
        r['id']: np.array(r['vector'], dtype=np.float64)
        for _, r in desc_tab.iterrows()
    }
    title_vecs = {
        t: id_to_vec[title_to_id[t]]
        for t in titles
        if t in title_to_id and title_to_id[t] in id_to_vec
    }
    missing_vec = [t for t in titles if t not in title_vecs]
    if missing_vec:
        print(f'[warn] {len(missing_vec)} palace titles missing vectors '
              f'(sample: {missing_vec[:5]})')

    pages = build_page_bodies(pagesplit)
    title_pages = build_entity_pages(titles, pages)

    raw_captions = parse_captions(cap_path)
    pngs = list_pngs(fig_dir)
    if len(raw_captions) != len(pngs):
        raise SystemExit(
            f'STOP: caption count {len(raw_captions)} != png count {len(pngs)}'
        )

    rows: list[dict] = []
    for cap, (png_path, page, idx) in zip(raw_captions, pngs):
        for cap_title, cap_full in detect_joined_caption(cap):
            rows.append({
                'png': png_path.relative_to(REPO).as_posix(),
                'page': page, 'idx': idx,
                'cap_title': cap_title, 'caption': cap_full,
            })

    unique_caps = sorted({r['caption'] for r in rows})
    vecs = embed_captions(unique_caps)
    cap_to_vec = {t: vecs[i] for i, t in enumerate(unique_caps)}

    for r in rows:
        cap_vec = cap_to_vec[r['caption']]
        cap_tokens = tokenize_caption(r['cap_title'])
        r['cap_tokens'] = cap_tokens
        page_window = {r['page'] + d for d in range(-PAGE_WINDOW, PAGE_WINDOW + 1)}
        cand_1st = [
            t for t in titles
            if title_pages.get(t) and (title_pages[t] & page_window)
        ]
        bt, bs, bm = (None, -1e9, {})
        if cand_1st:
            bt, bs, bm = best_in(cand_1st, cap_tokens, cap_vec,
                                 title_vecs, title_to_degree, max_degree)
        if bt is not None and bs >= THRESHOLD_LOCAL:
            r['tier'] = '1차'
            r['match'] = bt
            r['score'] = bs
            r['meta'] = bm
            continue
        bt2, bs2, bm2 = best_in(titles, cap_tokens, cap_vec,
                                title_vecs, title_to_degree, max_degree)
        if bt2 is not None and bs2 >= THRESHOLD_CASCADE:
            r['tier'] = '캐스케이드'
            r['match'] = bt2
            r['score'] = bs2
            r['meta'] = bm2
        else:
            r['tier'] = '미배치'
            r['match'] = None
            r['score'] = bs2 if bt2 is not None else bs
            r['meta'] = bm2 if bt2 is not None else bm

    by_node: dict[str, list[dict]] = {}
    for r in rows:
        if r['match']:
            by_node.setdefault(r['match'], []).append(r)
    for node, lst in by_node.items():
        if len(lst) <= 1:
            continue
        lst.sort(key=lambda x: x['score'], reverse=True)
        for loser in lst[1:]:
            loser['tier'] = '미배치 (충돌)'
            loser['match'] = None

    DATE = date.today().isoformat()
    out_tag = args.tag
    prev_tag = args.prev_tag
    out_md = (
        out_dir / f'{DATE}_image_match_accuracy_{out_tag}.md'
        if out_tag
        else out_dir / f'{DATE}_image_match_accuracy.md'
    )
    prev_md = (
        out_dir / f'{DATE}_image_match_accuracy_{prev_tag}.md'
        if prev_tag
        else out_dir / f'{DATE}_image_match_accuracy.md'
    )

    md_lines = [
        f'# image-caption matching accuracy ({DATE}, {out_tag or "no-tag"})',
        '',
        f'- palace: `{palace_path.relative_to(REPO).as_posix()}`',
        f'- snapshot: `{snapshot.relative_to(REPO).as_posix()}`',
        f'- figures dir: `{fig_dir.relative_to(REPO).as_posix()}`',
        f'- captions: `{cap_path.relative_to(REPO).as_posix()}`',
        f'- pagesplit: `{pagesplit.relative_to(REPO).as_posix()}`',
        f'- T_local = {THRESHOLD_LOCAL}, T_cascade = {THRESHOLD_CASCADE}, '
        f'name bonus = +{NAME_MATCH_BONUS}, hub max = -{HUB_PENALTY_MAX}, '
        f'page window = +/-{PAGE_WINDOW}, min_name_len = {MIN_NAME_LEN}',
        f'- name-match: whitespace tokens from TITLE only (trailing '
        f'parenthetical stripped) + exact/prefix (symmetric), '
        f'length-1 tokens & ent titles excluded',
        f'- rows: {len(rows)} (figures: {len(pngs)}, palace nodes: {len(nodes)})',
        '',
        '| # | 제목 | 페이지 | 파일 | 매칭 노드 | tier | 점수 | 근거 |',
        '|---:|---|---:|---|---|---|---:|---|',
    ]
    for i, r in enumerate(rows, 1):
        md_lines.append(
            f'| {i} | {r["cap_title"]} | {r["page"]} | '
            f'`{r["png"]}` | {r["match"] or "-"} | {r["tier"]} | '
            f'{r["score"]:.3f} | {signal_str(r["meta"])} |'
        )

    diff_section = _build_diff_section(prev_md, rows)
    if diff_section:
        md_lines.append('')
        md_lines.extend(diff_section)

    out_md.write_text('\n'.join(md_lines), encoding='utf-8')

    print('=' * 110)
    print(f'{"#":>3}  {"제목":<22} {"p":>3}  {"매칭 노드":<22} {"tier":<14} '
          f'{"점수":>7}  근거')
    print('-' * 110)
    for i, r in enumerate(rows, 1):
        ctitle = (r['cap_title'][:20] + '..') if len(r['cap_title']) > 22 else r['cap_title']
        match = r['match'] or '-'
        match = (match[:20] + '..') if len(match) > 22 else match
        print(f'{i:>3}  {ctitle:<22} {r["page"]:>3}  {match:<22} '
              f'{r["tier"]:<14} {r["score"]:>7.3f}  {signal_str(r["meta"])}')
    n_t1 = sum(1 for r in rows if r['tier'] == '1차')
    n_casc = sum(1 for r in rows if r['tier'] == '캐스케이드')
    n_unp = sum(1 for r in rows if r['tier'].startswith('미배치'))
    print('-' * 110)
    print(f'1차={n_t1}  캐스케이드={n_casc}  미배치={n_unp}  '
          f'(T_local={THRESHOLD_LOCAL}, T_cascade={THRESHOLD_CASCADE})')
    print(f'\nwrote: {out_md.relative_to(REPO).as_posix()}')

    if args.write_palace:
        out_palace, out_unplaced, im_meta = write_palace_copy(
            palace_path, rows,
            out_dir=Path(args.palace_out_dir) if args.palace_out_dir else None,
        )
        print(f'\n[write-palace] attached_nodes={im_meta["attached_nodes"]}, '
              f'attached_figures={im_meta["attached_figures"]}, '
              f'unplaced={im_meta["unplaced_figures"]}')
        print(f'  {out_palace.relative_to(REPO).as_posix()}')
        print(f'  {out_unplaced.relative_to(REPO).as_posix()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
