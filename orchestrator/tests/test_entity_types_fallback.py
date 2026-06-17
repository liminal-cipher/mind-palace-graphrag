"""Unit tests for orchestrator.entity_types generic fallback.

Deterministic, no LLM, no network. Covers the two fallback guarantees added to
the live upload path:
  - _apply_generic_fallback neutralizes ALL three type-bearing prompts
    (extract_graph / summarize_descriptions / community_report_graph), not just
    extract_graph, so a non-Korean upload taking the fallback loses the stock
    "한국사 전문가/historian/조선" tone in every index prompt.
  - a prompt-tune discover timeout (subprocess.TimeoutExpired) is caught and
    routed to the same generic fallback with reason="timeout".

Run:
    python orchestrator/tests/test_entity_types_fallback.py
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from orchestrator import entity_types as et  # noqa: E402
from orchestrator import index_root  # noqa: E402

# stock 프롬프트가 폴백 전 root 에 깔려 있다고 가정하는 국사 편향 토큰. 중립화 뒤엔
# 세 프롬프트 어디에도 남으면 안 된다.
HISTORIAN_TOKENS = ("한국사", "조선", "역사학", "historian", "Korean history")

PROMPT_NAMES = (
    index_root.EXTRACT_PROMPT_NAME,
    index_root.SUMMARIZE_PROMPT_NAME,
    index_root.COMMUNITY_GRAPH_PROMPT_NAME,
)


def _mk_root_with_historian_prompts() -> Path:
    """임시 인덱싱 root(prompts/ 에 historian 톤 3종)를 만들어 경로를 반환한다."""
    root = Path(tempfile.mkdtemp(prefix="et_fallback_"))
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    seed = (
        "You are an expert digital historian specializing in Korean history.\n"
        "조선 왕조의 인물과 사건을 분석한다. (역사학 전문)\n"
    )
    for name in PROMPT_NAMES:
        (prompts / name).write_text(seed, encoding="utf-8")
    return root


def _assert_neutralized(root: Path) -> None:
    prompts = root / "prompts"
    for name in PROMPT_NAMES:
        text = (prompts / name).read_text(encoding="utf-8")
        assert text != "", f"{name} was emptied"
        low = text.lower()
        for tok in HISTORIAN_TOKENS:
            assert tok.lower() not in low, f"{name} still contains historian token {tok!r}"


def test_fallback_neutralizes_all_three_prompts():
    """_apply_generic_fallback overwrites all three type-bearing prompts with the
    graphrag neutral defaults; no historian tone survives in any of them."""
    root = _mk_root_with_historian_prompts()
    try:
        res = et._apply_generic_fallback(root, "test")
        assert res.source == "fallback:test", res.source
        assert res.entity_types == et.GENERIC_ENTITY_TYPES
        _assert_neutralized(root)
        # settings.yaml 도 generic entity_types 로 렌더됐는지(존재 + 토큰 치환됨).
        settings = (root / "settings.yaml").read_text(encoding="utf-8")
        assert "__ENTITY_TYPES__" not in settings
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_discover_timeout_routes_to_timeout_fallback():
    """A prompt-tune discover timeout is caught and routed to the generic
    fallback with reason='timeout' (same path as an rc!=0 failure)."""
    root = _mk_root_with_historian_prompts()
    original = et.subprocess.run

    def _boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="graphrag prompt-tune", timeout=kwargs.get("timeout", 0),
        )

    et.subprocess.run = _boom
    try:
        res = et.resolve_entity_types(root, "임의도메인")
        assert res.source == "fallback:timeout", res.source
        assert res.entity_types == et.GENERIC_ENTITY_TYPES
        # 타임아웃 폴백도 세 프롬프트를 중립화해야 한다.
        _assert_neutralized(root)
    finally:
        et.subprocess.run = original
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------

def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
