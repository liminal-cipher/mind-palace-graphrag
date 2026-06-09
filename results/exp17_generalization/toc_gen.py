"""exp17 Phase B step 4: LLM-generated TOC, grounded by char offset.

Asks the LLM (gpt-4.1-mini, temp=0) to read the full corpus and emit
5-6 ordered sections. Each section payload:
    name        -- short Korean label
    start_marker -- one verbatim line from the corpus that opens the section

We do not trust the LLM to compute offsets; we recover `start_offset` by
running `text.find(start_marker)` after stripping the marker. Markers must
resolve uniquely or, if not unique, the first occurrence is taken. We
verify the sections are strictly ordered (offset increasing) and that no
two share the same offset. The first section's offset is forced to 0 so
content before the first marker is owned by section 1.

Output: results/exp17_generalization/toc_llm.json  (snapshot, deterministic)

This is a STOP-and-report step. After running, the script prints the
section table and waits for human review before downstream consumers
read it.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
CORPUS = REPO / 'input' / 'ai_gyoan' / 'AI_교안_정제.txt'
OUT = ROOT / 'toc_llm.json'

sys.path.insert(0, str(REPO / 'results' / 'exp10_room_gen'))
from room_gen import call_json, make_azure_client  # noqa: E402

MODEL = 'gpt-4.1-mini'

SYS_PROMPT = (
    '당신은 학습 자료 분석가다. 한국어 강의 자료(슬라이드 텍스트)를 읽고, '
    '자료 전체를 학습 흐름이 보존되는 5~6개의 순서 있는 섹션으로 묶어라.\n'
    '\n'
    '규칙:\n'
    '- 섹션 수는 5 또는 6. 그 외는 출력하지 마라.\n'
    '- 각 섹션의 이름(name)은 학습 주제를 짧게(15자 이내) 한국어로.\n'
    '- 각 섹션 시작점은 자료에 그대로 존재하는 한 줄(start_marker)로 지정. '
    '문장이 아니라 슬라이드 헤더처럼 짧은 줄이 좋다. 한 글자도 바꾸지 마라. '
    '공백·구두점·괄호도 자료 원문과 정확히 같아야 한다.\n'
    '- start_marker는 자료에 한 번만 나오는 줄이면 가장 좋다. 반복되는 헤더는 '
    '피하고 가능한 그 섹션에서만 등장하는 줄을 골라라.\n'
    '- 섹션은 자료의 등장 순서대로. 학습 흐름과 자료 순서가 일치해야 한다.\n'
    '- 첫 섹션은 자료 도입(통계학 정의 등)을 포함한다. 마지막 섹션은 자료 끝까지 덮는다.\n'
    '- 섹션 1개에 슬라이드 1장만 들어가는 잘게 자른 목차는 피하라. 자료 전체를 5~6개로 묶는 게 목적이다.'
)


def build_user_prompt(text: str) -> str:
    return (
        '자료:\n'
        '"""\n'
        f'{text}\n'
        '"""\n\n'
        '출력 JSON:\n'
        '{\n'
        '  "sections": [\n'
        '    {"name": "...", "start_marker": "자료 원문 한 줄"},\n'
        '    ...\n'
        '  ]\n'
        '}'
    )


def resolve_offsets(text: str, sections: list[dict]) -> tuple[list[dict], list[str]]:
    """Return enriched sections (with start_offset) and a list of warnings.

    For each section after the first, we take the earliest marker occurrence
    that is strictly greater than the previous section's start_offset. This
    enforces monotonicity deterministically when LLM markers happen to
    appear multiple times in the corpus (short or repeated slide headers).
    The first section's offset is forced to 0 so any preamble before the
    first marker is owned by section 1.
    """
    warnings: list[str] = []
    out: list[dict] = []
    prev_off = -1
    for i, sec in enumerate(sections):
        raw_marker = str(sec.get('start_marker', ''))
        marker = raw_marker.rstrip('\n')

        # Total occurrences (whole-corpus) for reporting.
        n_hits = text.count(marker) if marker else 0
        # Try exact first, then stripped fallback.
        search_marker = marker
        match_strategy = 'exact'
        # Earliest occurrence at-or-after prev_off + 1.
        offset = text.find(search_marker, max(0, prev_off + 1)) if marker else -1
        if offset < 0:
            stripped = marker.strip()
            if stripped:
                offset = text.find(stripped, max(0, prev_off + 1))
                if offset >= 0:
                    match_strategy = 'stripped'
                    search_marker = stripped
        if offset < 0:
            warnings.append(
                f'section {i + 1} ({sec.get("name", "")!r}): '
                f'start_marker not found at-or-after offset {prev_off + 1}: {marker!r}'
            )
            match_strategy = 'unresolved'

        if i == 0:
            offset = 0
            match_strategy = 'forced_zero (first section)'

        out.append({
            'idx': i,
            'name': str(sec.get('name', '')).strip(),
            'start_marker': marker,
            'start_offset': offset,
            'match_strategy': match_strategy,
            'marker_occurrences_in_corpus': n_hits,
        })
        if offset >= 0:
            prev_off = offset
    return out, warnings


def main() -> None:
    text = CORPUS.read_text(encoding='utf-8')
    client = make_azure_client()
    user_p = build_user_prompt(text)

    raw, usage = call_json(client, MODEL, SYS_PROMPT, user_p)
    obj = json.loads(raw)
    sections_raw = obj.get('sections', [])
    if not isinstance(sections_raw, list) or not (5 <= len(sections_raw) <= 6):
        print(f'STOP: LLM returned {len(sections_raw)} sections, expected 5 or 6')
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        sys.exit(2)

    sections, warnings = resolve_offsets(text, sections_raw)

    # Order/monotonicity checks.
    offsets = [s['start_offset'] for s in sections]
    monotonic = all(offsets[i] < offsets[i + 1]
                    for i in range(len(offsets) - 1)
                    if offsets[i] >= 0 and offsets[i + 1] >= 0)
    distinct = len(set(o for o in offsets if o >= 0)) == sum(1 for o in offsets if o >= 0)

    # Section spans: section i covers [start_offset_i, start_offset_{i+1});
    # the last covers [start_offset_last, len(text)).
    for i, s in enumerate(sections):
        s['end_offset'] = sections[i + 1]['start_offset'] if i + 1 < len(sections) else len(text)
        s['length_chars'] = max(0, s['end_offset'] - s['start_offset']) if s['start_offset'] >= 0 else 0

    payload = {
        'meta': {
            'corpus': str(CORPUS.relative_to(REPO)).replace('\\', '/'),
            'corpus_chars': len(text),
            'model': MODEL,
            'temperature': 0,
            'ts': datetime.now(timezone.utc).isoformat(),
            'usage': usage,
            'n_sections': len(sections),
            'monotonic_offsets': monotonic,
            'distinct_offsets': distinct,
            'warnings': warnings,
        },
        'sections': sections,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    # Pretty STOP-and-report
    print('=== exp17 LLM TOC (review before downstream use) ===')
    print(f'corpus: {payload["meta"]["corpus"]} ({len(text)} chars)')
    print(f'sections: {len(sections)} | monotonic: {monotonic} | distinct: {distinct}')
    if warnings:
        for w in warnings:
            print(f'  WARN: {w}')
    print()
    print(f'{"#":>2}  {"start":>5}  {"end":>5}  {"chars":>5}  name  |  start_marker')
    for s in sections:
        print(
            f'{s["idx"] + 1:>2}  {s["start_offset"]:>5}  {s["end_offset"]:>5}  '
            f'{s["length_chars"]:>5}  {s["name"]}  |  {s["start_marker"]}'
        )
    print()
    print(f'usage: prompt={usage["prompt_tokens"]} completion={usage["completion_tokens"]}')
    print(f'written: {OUT.relative_to(REPO)}')


if __name__ == '__main__':
    main()
