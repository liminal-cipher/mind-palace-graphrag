"""
4 메서드 warm sweep: 같은 질문에 local/global/drift/basic 적용 후 답·시간·token·비용 측정.
결과는 results/audit/ 에 md + json으로 저장.

옵션:
  --profile {default,short}   default = settings.yaml 그대로. short = audit 표본 2 단축판.
  --model NAME                Azure deployment 이름 override (예: gpt-4.1, gpt-5.4-mini).
                              생략 시 settings.yaml 의 default_completion_model 사용.
  --skip-drift                drift 메서드만 건너뛰기 (default profile + 큰 모델 조합 시간 절감).
  --query "..."               질문 override. 생략 시 audit 표본 2와 같은 세종 질문.
  --tag NAME                  결과 파일명에 붙일 태그 (구분용).

단가 (cost 계산):
  gpt-4.1-mini : $0.40 / $1.60  (메모)
  gpt-4.1      : $2.00 / $8.00  (OpenAI 공개가 기준 가정)
  그 외 모델   : 단가 미상 → cost 빈칸, raw token 만 저장.

예시:
  python exp_method_sweep.py --profile default
  python exp_method_sweep.py --profile default --model gpt-4.1
  python exp_method_sweep.py --profile default --model gpt-5.4-mini --skip-drift
"""

import argparse
import asyncio
import datetime as _dt
import json
import time
from pathlib import Path

import warm_query as wq

# (input_per_M, output_per_M) USD. None = 단가 미상.
PRICING: dict[str, tuple[float, float] | None] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
}


def cost_for(model: str, prompt_tok: int, out_tok: int) -> float | None:
    p = PRICING.get(model)
    if p is None:
        return None
    inp, out = p
    return prompt_tok / 1e6 * inp + out_tok / 1e6 * out


def apply_profile(profile: str) -> dict:
    ls = wq.config.local_search
    gs = wq.config.global_search
    ds = wq.config.drift_search
    bs = wq.config.basic_search
    if profile == "short":
        ls.top_k_entities = 5
        ls.top_k_relationships = 5
        ls.max_context_tokens = 6000
        gs.max_context_tokens = 6000
        gs.map_max_length = 500
        gs.reduce_max_length = 1000
        ds.drift_k_followups = 10
        ds.n_depth = 2
        bs.k = 5
        bs.max_context_tokens = 6000
        wq.RESPONSE_TYPE = "Single Paragraph"
    elif profile == "default":
        # settings.yaml 그대로. response_type은 CLI 기본값.
        wq.RESPONSE_TYPE = "Multiple Paragraphs"
    else:
        raise ValueError(f"unknown profile: {profile}")
    return {
        "local": {"top_k_entities": ls.top_k_entities,
                  "top_k_relationships": ls.top_k_relationships,
                  "max_context_tokens": ls.max_context_tokens,
                  "response_type": wq.RESPONSE_TYPE},
        "global": {"max_context_tokens": gs.max_context_tokens,
                   "map_max_length": gs.map_max_length,
                   "reduce_max_length": gs.reduce_max_length,
                   "response_type": wq.RESPONSE_TYPE},
        "drift": {"drift_k_followups": ds.drift_k_followups,
                  "n_depth": ds.n_depth,
                  "response_type": wq.RESPONSE_TYPE},
        "basic": {"k": bs.k, "max_context_tokens": bs.max_context_tokens,
                  "response_type": wq.RESPONSE_TYPE},
    }


def apply_model(deployment: str | None) -> str:
    """default_completion_model 의 model + azure_deployment_name 둘 다 override."""
    cfg = wq.config.completion_models["default_completion_model"]
    if deployment:
        cfg.model = deployment
        cfg.azure_deployment_name = deployment
    return cfg.model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["default", "short"], default="short")
    ap.add_argument("--model", default=None,
                    help="Azure deployment 이름 (생략 시 settings.yaml 의 model)")
    ap.add_argument("--skip-drift", action="store_true")
    ap.add_argument("--methods", default=None,
                    help="콤마 구분 메서드 (예: drift 또는 basic,local). "
                         "생략 시 4 메서드 모두 (skip-drift 영향).")
    ap.add_argument("--query", default="세종대왕의 업적은 무엇인가?")
    ap.add_argument("--tag", default=None, help="파일명 구분용 태그")
    ap.add_argument("--warmup", action="store_true",
                    help="첫 측정 전 같은 메서드로 throwaway 1회 (LiteLLM connection 등 warm).")
    args = ap.parse_args()

    knobs = apply_profile(args.profile)
    model = apply_model(args.model)
    wq.ENGINES.clear()  # mutation 반영되게 엔진 캐시 비움

    all_methods = ["basic", "local", "global", "drift"]
    if args.methods:
        methods = [m.strip() for m in args.methods.split(",") if m.strip()]
        bad = [m for m in methods if m not in all_methods]
        if bad:
            ap.error(f"unknown method(s): {bad}. choose from {all_methods}")
    else:
        methods = [m for m in all_methods if not (args.skip_drift and m == "drift")]

    print(f"\n=== sweep: profile={args.profile}, model={model}, "
          f"methods={methods}, query={args.query!r}, warmup={args.warmup} ===\n")

    if args.warmup and methods:
        first = methods[0]
        print(f"--- warmup ({first}) [discarded] ---")
        eng = wq._engine(first)
        t = time.perf_counter()
        asyncio.run(eng.search(args.query))
        print(f"  warmup done in {time.perf_counter() - t:.1f}s\n")

    results = []
    for method in methods:
        print(f"--- {method} ---")
        t_build = time.perf_counter()
        eng = wq._engine(method)
        build_dt = time.perf_counter() - t_build

        t = time.perf_counter()
        try:
            r = asyncio.run(eng.search(args.query))
            dt = time.perf_counter() - t
            resp_text = r.response if isinstance(r.response, str) else str(r.response)
            c = cost_for(model, r.prompt_tokens, r.output_tokens)
            results.append({
                "method": method,
                "build_time": round(build_dt, 1),
                "time": round(dt, 1),
                "llm_calls": r.llm_calls,
                "prompt_tokens": r.prompt_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": round(c, 4) if c is not None else None,
                "response_len": len(resp_text),
                "response": resp_text,
                "error": None,
            })
            cost_str = f"${c:.4f}" if c is not None else "$ ?"
            print(f"  build={build_dt:.1f}s run={dt:.1f}s "
                  f"calls={r.llm_calls} prompt={r.prompt_tokens} out={r.output_tokens} {cost_str}")
        except Exception as e:
            dt = time.perf_counter() - t
            results.append({
                "method": method, "build_time": round(build_dt, 1),
                "time": round(dt, 1), "error": f"{type(e).__name__}: {e}",
                "llm_calls": None, "prompt_tokens": None, "output_tokens": None,
                "cost_usd": None, "response_len": 0, "response": "",
            })
            print(f"  [STOP] {type(e).__name__}: {e}")

    # 콘솔 요약
    print("\n=== 요약 ===")
    print(f"  {'method':8s} {'time':>7s} {'calls':>6s} {'prompt':>8s} "
          f"{'output':>7s} {'$':>9s} {'resp_len':>9s}")
    for r in results:
        cost_str = f"${r['cost_usd']:.4f}" if r['cost_usd'] is not None else "  $ ?  "
        print(f"  {r['method']:8s} {r['time']:6.1f}s "
              f"{str(r['llm_calls'] or '-'):>6s} "
              f"{str(r['prompt_tokens'] or '-'):>8s} "
              f"{str(r['output_tokens'] or '-'):>7s} "
              f"{cost_str:>9s} {r['response_len']:9d}")

    valid_costs = [r['cost_usd'] for r in results if r['cost_usd'] is not None]
    total_cost = sum(valid_costs) if valid_costs else None
    total_time = sum(r['time'] for r in results)
    cost_summary = f"cost=${total_cost:.4f}" if total_cost is not None else "cost=$?"
    print(f"\n  total: wall={total_time:.1f}s  {cost_summary}")

    # 파일 저장
    DATE = _dt.date.today().isoformat()
    OUT_DIR = Path(__file__).resolve().parent / "results" / "audit"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    model_slug = model.replace(".", "").replace("/", "_")
    base = f"{DATE}_method_sweep_warm_{args.profile}_{model_slug}{tag}"
    OUT_MD = OUT_DIR / f"{base}.md"
    OUT_JSON = OUT_DIR / f"{base}.json"

    pricing = PRICING.get(model)
    meta = {
        "date": DATE,
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "query": args.query,
        "snapshot": str(wq.SNAPSHOT.relative_to(Path(__file__).resolve().parent)),
        "profile": args.profile,
        "model": model,
        "community_level": wq.COMMUNITY_LEVEL,
        "pricing": (
            {"input_per_M_usd": pricing[0], "output_per_M_usd": pricing[1],
             "note": "embedding 비용 제외"}
            if pricing else {"note": "단가 미상 - cost 빈칸"}
        ),
        "knobs": knobs,
        "totals": {"wall_seconds": round(total_time, 1),
                   "cost_usd": round(total_cost, 4) if total_cost is not None else None},
        "results": results,
    }

    OUT_JSON.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def md_table(rows):
        head = "| 메서드 | wall | LLM calls | prompt tok | output tok | $ 비용 | 답 길이 |"
        sep = "|---|---:|---:|---:|---:|---:|---:|"
        lines = [head, sep]
        for r in rows:
            cost_str = f"${r['cost_usd']:.4f}" if r['cost_usd'] is not None else "?"
            prompt = f"{r['prompt_tokens']:,}" if r['prompt_tokens'] else "-"
            out = f"{r['output_tokens']:,}" if r['output_tokens'] else "-"
            calls = r['llm_calls'] if r['llm_calls'] else "-"
            line = (f"| {r['method']} | {r['time']:.1f}s | {calls} | "
                    f"{prompt} | {out} | {cost_str} | {r['response_len']}자 |")
            if r.get("error"):
                line += f" <!-- error: {r['error']} -->"
            lines.append(line)
        return "\n".join(lines)

    md_parts = [
        f"# method sweep warm: profile={args.profile}, model={model} ({DATE})",
        "",
        f"- 실행 시각: {meta['timestamp']}",
        f"- 질문: \"{args.query}\"",
        f"- 스냅샷: `{meta['snapshot']}`",
        f"- 프로파일: **{args.profile}**" + (
            " (audit 표본 2 단축판)" if args.profile == "short" else " (settings.yaml 기본값)"
        ),
        f"- 모델: **{model}**" + (
            f"  (단가 ${pricing[0]}/M in, ${pricing[1]}/M out)"
            if pricing else "  (단가 미상)"
        ),
        f"- community_level: {wq.COMMUNITY_LEVEL}",
        "",
        "## knobs",
        "```json",
        json.dumps(knobs, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 결과",
        "",
        md_table(results),
        "",
        f"- 합계: wall **{total_time:.1f}s**" + (
            f", cost **${total_cost:.4f}**" if total_cost is not None else ", cost ?"
        ),
        "",
        "## 답 전문",
    ]
    for r in results:
        cost_str = f"${r['cost_usd']:.4f}" if r['cost_usd'] is not None else "$?"
        head = f"### {r['method']} ({r['time']:.1f}s, {cost_str})"
        body = f"> {r['response']}" if r['response'] else (
            f"(실패: {r['error']})" if r.get("error") else "(빈 답)"
        )
        md_parts += ["", head, "", body]

    OUT_MD.write_text("\n".join(md_parts), encoding="utf-8")
    print(f"\n[saved] {OUT_MD.relative_to(Path(__file__).resolve().parent)}")
    print(f"[saved] {OUT_JSON.relative_to(Path(__file__).resolve().parent)}")


if __name__ == "__main__":
    main()
