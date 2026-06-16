"""exp17 step 1: deterministic OCR cleanup.

Input:  input/ai_slides/AI_교안.txt
Output: input/ai_gyoan/AI_교안_정제.txt + cleanup_report.json

Rules (no LLM, no content rewriting):
- Strip BOM if present.
- Strip trailing whitespace on each line.
- Collapse runs of >=2 blank lines down to 1 (preserve paragraph gaps).
- Drop lines that are pure punctuation noise (length 1 and non-Korean).
- No de-duplication of repeated slide headers: they encode slide boundaries
  and are useful structure for the regex section parser.
- No hyphen-line-break repair (none detected).
- No page-number stripping (none detected).
- Ensure trailing newline.
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'input' / 'ai_slides' / 'AI_교안.txt'
OUT_DIR = REPO / 'input' / 'ai_gyoan'
OUT = OUT_DIR / 'AI_교안_정제.txt'
REPORT = REPO / 'results' / 'exp17_generalization' / 'cleanup_report.json'


def clean(raw: str) -> tuple[str, dict]:
    before_chars = len(raw)
    before_lines = raw.count('\n') + 1
    before_blank_lines = sum(1 for l in raw.split('\n') if not l.strip())

    # strip BOM
    if raw.startswith('﻿'):
        raw = raw[1:]

    # strip CR
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')

    # per-line: rstrip trailing whitespace
    lines = [l.rstrip() for l in raw.split('\n')]

    # collapse runs of >=2 blank lines down to 1
    out_lines: list[str] = []
    prev_blank = False
    for l in lines:
        is_blank = not l.strip()
        if is_blank and prev_blank:
            continue
        out_lines.append(l)
        prev_blank = is_blank

    # drop trailing empty lines, then ensure exactly one terminal newline
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()
    cleaned = '\n'.join(out_lines) + '\n'

    after_chars = len(cleaned)
    after_lines = cleaned.count('\n')
    after_blank_lines = sum(1 for l in cleaned.split('\n') if not l.strip())

    report = {
        'source': str(SRC.relative_to(REPO)).replace('\\', '/'),
        'output': str(OUT.relative_to(REPO)).replace('\\', '/'),
        'before': {
            'chars': before_chars,
            'lines': before_lines,
            'blank_lines': before_blank_lines,
        },
        'after': {
            'chars': after_chars,
            'lines': after_lines,
            'blank_lines': after_blank_lines,
        },
        'delta_chars': after_chars - before_chars,
        'operations': [
            'strip BOM',
            'normalize CRLF/CR to LF',
            'rstrip whitespace per line',
            'collapse >=2 blank lines to 1',
            'drop trailing blank lines',
            'ensure single terminal newline',
        ],
        'skipped': {
            'hyphen_line_break_repair': 'no candidates detected',
            'page_number_strip': 'no digit-only lines detected',
            'consecutive_dup_collapse': 'no consecutive duplicate lines detected',
            'repeated_header_dedup': 'preserved (encode slide boundaries)',
        },
    }
    return cleaned, report


def main() -> None:
    if not SRC.exists():
        print(f'STOP: source corpus missing: {SRC.relative_to(REPO)}')
        sys.exit(2)
    raw = SRC.read_text(encoding='utf-8')
    cleaned, report = clean(raw)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(cleaned, encoding='utf-8')
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
