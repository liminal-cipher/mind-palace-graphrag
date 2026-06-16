"""Normalize a preprocessing result dir into the indexing/matching input contract.

preprocessing/result/<domain>_v1/ (pipeline_v2 output) -> input/<domain>/ with the
fixed names graphrag + palace.match_images expect:

    txt/content.txt        -> corpus.txt        (graphrag index corpus)
    txt/content_paged.txt  -> pagesplit.txt      (verbatim; [pageN] is the canonical marker)
    txt/caption.txt        -> captions.md        ([pageN] text -> <figcaption>text</figcaption>)
    img/*.png              -> images/            (figures for match_images)

The page-marker format is "[pageN]" end-to-end (preprocessing pipeline_v2 emits it,
palace.match_images PAGE_MARKER_RE parses it), so pagesplit is copied unchanged.

This replaces the old manual copy/rename step so the result->input handoff is
one deterministic command. input/ is gitignored (저작물); this only rewrites the
working tree for indexing.

Usage:
    python -m preprocessing.normalize --result preprocessing/result/통계_기초_v1 --domain statistics
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE_TAG = re.compile(r"\[page(\d+)\]")


def _captions_to_md(text: str) -> str:
    # Each non-empty line "[pageN] caption" -> "<figcaption>caption</figcaption>".
    # match_images pairs captions to PNGs by order, so one figcaption per figure line.
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cap = PAGE_TAG.sub("", line).strip().strip('"')
        out.append(f"<figcaption>{cap}</figcaption>")
    return "\n\n".join(out) + "\n"


def normalize(result_dir: Path, domain: str) -> Path:
    txt = result_dir / "txt"
    content = txt / "content.txt"
    paged = txt / "content_paged.txt"
    caption = txt / "caption.txt"
    img_src = result_dir / "img"
    for p in (content, paged, caption):
        if not p.exists():
            raise SystemExit(f"STOP: missing {p.relative_to(REPO)}")

    out = REPO / "input" / domain
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.txt").write_text(content.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "pagesplit.txt").write_text(
        paged.read_text(encoding="utf-8"), encoding="utf-8"  # [pageN] kept verbatim
    )
    (out / "captions.md").write_text(
        _captions_to_md(caption.read_text(encoding="utf-8")), encoding="utf-8"
    )

    img_dst = out / "images"
    if img_dst.exists():
        shutil.rmtree(img_dst)
    img_dst.mkdir(parents=True, exist_ok=True)
    n_img = 0
    if img_src.is_dir():
        for png in sorted(img_src.glob("*.png")):
            shutil.copy2(png, img_dst / png.name)
            n_img += 1

    n_cap = (out / "captions.md").read_text(encoding="utf-8").count("<figcaption>")
    print(f"normalized -> {out.relative_to(REPO).as_posix()}/")
    print(f"  corpus.txt, pagesplit.txt, captions.md (figs={n_cap}), images/ ({n_img} png)")
    if n_cap != n_img:
        print(f"  [warn] caption count {n_cap} != png count {n_img} "
              f"(match_images pairs by order and will STOP on mismatch)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True, help="preprocessing/result/<domain>_v1 dir")
    ap.add_argument("--domain", required=True, help="target input/<domain> name")
    args = ap.parse_args()
    result_dir = Path(args.result)
    if not result_dir.is_absolute():
        result_dir = REPO / result_dir
    normalize(result_dir, args.domain)


if __name__ == "__main__":
    main()
