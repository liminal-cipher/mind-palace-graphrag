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
# 도메인별 입력/스냅샷 경로는 잡마다 다르므로 자동 기본값을 두지 않는다(특정 도메인으로
# 조용히 떨어지지 않게): 호출 시 명시한다. 출력 dir 만 도메인 무관이라 기본값 유지.
DEFAULT_OUT_DIR = REPO / 'docs' / 'audit'

CAPTION_TAG_RE = re.compile(r'<figcaption>(.*?)</figcaption>', re.DOTALL)
SPLIT_BAR_RE = re.compile(r'\s*[|￨ㅣ]\s*')  # ASCII bar, halfwidth bar, hangul I
PAGE_MARKER_RE = re.compile(r'\[page(\d+)\]\n?')  # preprocessing pipeline_v2 format
FIG_NAME_RE = re.compile(r'fig_(\d+)_(\d+)\.png$')
# STEP4 분리 자식(fig_p_i_cv_k.png)까지 page/idx 를 뽑기 위한 관대한 패턴(정렬·표시용).
FIG_NAME_RE_ANY = re.compile(r'fig_(\d+)_(\d+)(?:_cv_(\d+))?\.png$')
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


def figure_rows_from_json(figures_json: Path) -> list[dict]:
    """전처리 meta/figures.json(단일 진실원본)에서 매칭 행을 만든다.

    각 figure 레코드가 img_path + caption + page 를 들고 있으므로, STEP4 분리 자식
    (fig_p_i_cv_k)도 자기 캡션과 함께 그대로 흘러간다. 옛 경로(캡션파일 + 파일명
    정규식 + 위치 zip)와 달리 파일명 패턴·순서에 의존하지 않는다. write_palace_copy 가
    `REPO / png` 로 이미지를 복사하므로 png 는 repo-상대 posix 로 둔다(figures.json 의
    img_path 는 'images/<file>' 상대 → figures.json 부모의 부모(preprocess dir) 기준).
    캡션 없는 figure 도 갤러리(미배치)에 남도록 빈 캡션 행으로 포함한다."""
    figs = json.loads(figures_json.read_text(encoding='utf-8'))
    base = figures_json.parent.parent  # <preprocess>/meta/figures.json -> <preprocess>
    rows: list[dict] = []
    for fig in figs:
        rel = fig.get('img_path')
        if not rel:
            continue
        png_abs = (base / rel).resolve()
        if not png_abs.exists():
            continue
        png_repo_rel = png_abs.relative_to(REPO).as_posix()
        page = int(fig.get('page') or 0)
        m = FIG_NAME_RE_ANY.match(png_abs.name)
        idx = int(m.group(2)) if m else 0
        cap = (fig.get('caption') or '').strip()
        pairs = detect_joined_caption(cap) if cap else []
        if not pairs:
            pairs = [('', '')]
        for cap_title, cap_full in pairs:
            rows.append({
                'png': png_repo_rel, 'page': page, 'idx': idx,
                'cap_title': cap_title, 'caption': cap_full,
            })
    rows.sort(key=lambda r: (r['page'], r['idx']))
    return rows


def match_and_write(
    palace_path: Path,
    snapshot: Path,
    figures_json: Path,
    pagesplit: Path,
    out_dir: Path | None = None,
) -> tuple[Path, Path, dict]:
    """figures.json 기반 이미지↔노드 매칭 후 palace_with_images.json +
    unplaced_figures.json 를 out_dir(없으면 palace 옆)에 쓴다. audit md 는 만들지
    않는다(데모/라이브 전용). 캡션 임베딩(text-embedding-3-small) 호출이 있어 Azure
    자격증명(GRAPHRAG_API_KEY/BASE)이 필요하다. 매칭 로직(임계값·이름가산·허브감점·
    페이지윈도·충돌해소)은 기존과 동일. CLI(main)와 오케스트레이터가 공유한다."""
    nodes = load_palace_nodes(palace_path)
    titles = sorted(nodes.keys())

    ents_df = pd.read_parquet(snapshot / 'entities.parquet')
    title_to_id = dict(zip(ents_df['title'], ents_df['id']))
    title_to_degree = {t: int(d) for t, d in zip(ents_df['title'], ents_df['degree'])}
    max_degree = int(ents_df['degree'].max()) if len(ents_df) else 0

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

    rows = figure_rows_from_json(figures_json)

    unique_caps = sorted({r['caption'] for r in rows if r['caption'].strip()})
    cap_to_vec: dict[str, np.ndarray] = {}
    if unique_caps:
        vecs = embed_captions(unique_caps)
        cap_to_vec = {t: vecs[i] for i, t in enumerate(unique_caps)}

    for r in rows:
        # 캡션 없는 figure 는 매칭 불가 → 미배치(갤러리). 빈 문자열 임베딩 회피.
        if not r['caption'].strip():
            r['tier'], r['match'], r['score'], r['meta'] = '미배치', None, 0.0, {}
            continue
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
            r['tier'], r['match'], r['score'], r['meta'] = '1차', bt, bs, bm
            continue
        bt2, bs2, bm2 = best_in(titles, cap_tokens, cap_vec,
                                title_vecs, title_to_degree, max_degree)
        if bt2 is not None and bs2 >= THRESHOLD_CASCADE:
            r['tier'], r['match'], r['score'], r['meta'] = '캐스케이드', bt2, bs2, bm2
        else:
            r['tier'] = '미배치'
            r['match'] = None
            r['score'] = bs2 if bt2 is not None else bs
            r['meta'] = bm2 if bt2 is not None else bm

    # 충돌 해소: 한 노드에 여러 figure 가 붙으면 최고점만 남기고 나머지는 미배치(충돌).
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

    return write_palace_copy(palace_path, rows, out_dir=out_dir)


def main() -> int:
    ap = argparse.ArgumentParser(
        description='figures.json 기반 이미지↔palace 노드 매칭 → '
                    'palace_with_images.json + unplaced_figures.json')
    ap.add_argument('--palace', required=True,
                    help='palace.json (예: var/jobs/<id>/palace_out/<run>.palace.json)')
    ap.add_argument('--snapshot', required=True,
                    help='entities.parquet + lancedb 가 있는 스냅샷 dir')
    ap.add_argument('--figures-json', required=True,
                    help='전처리 meta/figures.json (단일 진실원본)')
    ap.add_argument('--pagesplit', required=True,
                    help='[pageN] 마커 본문 (전처리 txt/content_paged.txt)')
    ap.add_argument('--out-dir', default=None,
                    help='출력 dir (palace_with_images.json/unplaced_figures.json/images). '
                         '미지정 시 palace 옆.')
    args = ap.parse_args()

    _load_dotenv(REPO / '.env')
    out_palace, out_unplaced, meta = match_and_write(
        Path(args.palace).resolve(),
        Path(args.snapshot).resolve(),
        Path(args.figures_json).resolve(),
        Path(args.pagesplit).resolve(),
        out_dir=Path(args.out_dir).resolve() if args.out_dir else None,
    )
    print(f'[match_images] caption_rows={meta["caption_rows"]} '
          f'attached_nodes={meta["attached_nodes"]} '
          f'attached_figures={meta["attached_figures"]} '
          f'unplaced={meta["unplaced_figures"]}')
    print(f'  {out_palace.relative_to(REPO).as_posix()}')
    print(f'  {out_unplaced.relative_to(REPO).as_posix()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
