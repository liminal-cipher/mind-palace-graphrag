"""TOC generator: LLM-emit ordered sections, ground by string-find offset.

Adapted from results/exp17_generalization/toc_gen.py. The exp17 file
hardcoded a corpus path for the AI 교안 study; palace passes the corpus
path as a function argument so a single config drives a different
domain (한국사, AI 교안, etc.).

Public API:
    generate_toc(corpus_path, out_path, model, client, sys_prompt) -> dict
    resolve_offsets(text, sections) -> (sections, warnings)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from palace.room_gen import call_json, make_azure_client


SYS_PROMPT_TEMPLATE = (
    '당신은 학습 자료 분석가다. 주어진 한국어 학습 자료를 읽고, '
    '자료 전체를 학습 흐름이 보존되는 순서 있는 섹션으로 묶어라.\n'
    '{domain_line}'
    '\n'
    '규칙:\n'
    '- 섹션 수는 자료에 맞게 1개에서 최대 {max_rooms}개 사이로 자연스럽게 정하라. '
    '자료 내용이 섹션 수를 정하되, 절대 {max_rooms}개를 넘기지 마라. 주제가 더 많아 '
    '보여도 관련된 것끼리 묶어 {max_rooms}개 이하로 만들어라.\n'
    '- 각 섹션의 이름(name)은 학습 주제를 짧게(15자 이내) 한국어로.\n'
    '- 각 섹션 시작점은 자료에 그대로 존재하는 한 줄(start_marker)로 지정. '
    '제목이나 헤더처럼 짧은 줄이 좋다. start_marker는 자료 원문에서 한 줄을 '
    '그대로 복사한 문자열이어야 한다. 한 글자도 바꾸거나 다듬거나 요약하지 마라. '
    '공백·구두점·괄호·대소문자까지 자료 원문과 정확히 같아야 한다.\n'
    '- start_marker는 자료에 한 번만 나오는 줄이면 가장 좋다. 반복되는 헤더는 '
    '피하고 가능한 그 섹션에서만 등장하는 줄을 골라라.\n'
    '- 섹션은 자료의 등장 순서대로. 학습 흐름과 자료 순서가 일치해야 한다.\n'
    '- 첫 섹션은 자료의 도입부를 포함한다. 마지막 섹션은 자료 끝까지 덮는다.\n'
    '- 섹션 1개에 한 토막만 들어가는 잘게 자른 목차는 피하라. 자료 전체를 의미 단위로 묶는 게 목적이다.'
)


def build_sys_prompt(domain: str | None = None, max_rooms: int = 10) -> str:
    """Domain-neutral TOC system prompt. `domain` (optional) is woven in as a
    one-line hint so the same prompt drives any corpus; no domain framing is
    hardcoded in the template itself. `max_rooms` caps the requested section
    count; the deterministic clamp in generate_toc is the hard guarantee, this
    wording only lowers overflow frequency.
    """
    domain_line = f'\n자료의 도메인 힌트: {domain}\n' if domain else ''
    return SYS_PROMPT_TEMPLATE.format(domain_line=domain_line, max_rooms=max_rooms)


# Back-compat: a domain-neutral default for callers that import SYS_PROMPT.
SYS_PROMPT = build_sys_prompt()


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
    """For each section after the first, take the earliest marker occurrence
    strictly greater than the previous section's offset. First section is
    forced to 0 so any preamble is owned by section 1.
    """
    warnings: list[str] = []
    out: list[dict] = []
    prev_off = -1
    for i, sec in enumerate(sections):
        raw_marker = str(sec.get('start_marker', ''))
        marker = raw_marker.rstrip('\n')

        n_hits = text.count(marker) if marker else 0
        search_marker = marker
        match_strategy = 'exact'
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


def generate_toc(
    corpus_path: str | Path,
    out_path: str | Path | None,
    model: str,
    client=None,
    sys_prompt: str | None = None,
    corpus_rel: str | None = None,
    print_summary: bool = True,
    min_rooms: int = 1,
    max_rooms: int = 10,
    domain: str | None = None,
) -> dict:
    """Run the LLM TOC pass on `corpus_path`, validate marker grounding,
    and return the payload dict. If `out_path` is given, also writes the
    payload to disk. `corpus_rel` (optional) is the path string written
    into meta.corpus; useful so the JSON records a repo-relative path
    instead of an absolute filesystem path. `domain` (optional) is a
    free-text hint woven into the system prompt; ignored when an explicit
    `sys_prompt` is supplied.
    """
    corpus_path = Path(corpus_path)
    text = corpus_path.read_text(encoding='utf-8')
    if sys_prompt is None:
        sys_prompt = build_sys_prompt(domain, max_rooms)
    if client is None:
        client = make_azure_client()
    user_p = build_user_prompt(text)

    raw, usage = call_json(client, model, sys_prompt, user_p)
    obj = json.loads(raw)
    sections_raw = obj.get('sections', [])
    n_raw = len(sections_raw) if isinstance(sections_raw, list) else 0
    if not isinstance(sections_raw, list) or n_raw < min_rooms:
        print(f'STOP: LLM returned {n_raw} sections, expected at least {min_rooms}')
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        sys.exit(2)

    sections, warnings = resolve_offsets(text, sections_raw)

    # Overflow is not clamped here. The room-count cap is enforced downstream
    # in a single node-count-aware pass (build_rooms.absorb_empty_rooms), which
    # merges the smallest rooms into a neighbor after Stage B. The prompt still
    # asks for <= max_rooms sections as a soft hint; the cap is the hard
    # guarantee. A live run always reaches room generation regardless of count.
    offsets = [s['start_offset'] for s in sections]
    monotonic = all(offsets[i] < offsets[i + 1]
                    for i in range(len(offsets) - 1)
                    if offsets[i] >= 0 and offsets[i + 1] >= 0)
    distinct = len(set(o for o in offsets if o >= 0)) == sum(1 for o in offsets if o >= 0)

    for i, s in enumerate(sections):
        s['end_offset'] = sections[i + 1]['start_offset'] if i + 1 < len(sections) else len(text)
        s['length_chars'] = max(0, s['end_offset'] - s['start_offset']) if s['start_offset'] >= 0 else 0

    payload = {
        'meta': {
            'corpus': corpus_rel or str(corpus_path).replace('\\', '/'),
            'corpus_chars': len(text),
            'model': model,
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
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8',
        )

    if print_summary:
        print('=== LLM TOC (review before downstream use) ===')
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
        if out_path is not None:
            print(f'written: {out_path}')
    return payload
