"""
warm-loaded GraphRAG에서 default vs 단축판 local 검색 비교 실험.

목적: warm 상태에서 두 프로파일의 wall time, prompt/output token, 답 길이 비교.
CLI cold 호출은 매번 import + parquet + lancedb 재로딩 때문에 이런 반복 비교가
비싸서 못 했음. warm 로딩으로 같은 질문 N회 + 두 프로파일을 짧은 시간에 비교 가능.

프로파일 (audit 표본 2 기준):
  default: response_type "Multiple Paragraphs", top_k_entities=10, top_k_rel=10, max_ctx=12000
  short:   response_type "Single Paragraph",   top_k_entities=5,  top_k_rel=5,  max_ctx=6000

실행:
  .venv/Scripts/python.exe -X utf8 exp_warm_compare.py
"""

import asyncio
import statistics
import time

import warm_query as wq

PROFILES = {
    "default": {
        "response_type": "Multiple Paragraphs",
        "top_k_entities": 10,
        "top_k_relationships": 10,
        "max_context_tokens": 12000,
    },
    "short": {
        "response_type": "Single Paragraph",
        "top_k_entities": 5,
        "top_k_relationships": 5,
        "max_context_tokens": 6000,
    },
}

QUERIES = [
    "세종대왕의 업적은 무엇인가?",
    "이순신은 임진왜란에서 어떤 역할을 했나?",
]

N_TRIALS = 2


def build_local_with(profile: dict):
    ls = wq.config.local_search
    ls.top_k_entities = profile["top_k_entities"]
    ls.top_k_relationships = profile["top_k_relationships"]
    ls.max_context_tokens = profile["max_context_tokens"]
    wq.RESPONSE_TYPE = profile["response_type"]
    return wq._build_local()


def run_one(engine, query: str) -> dict:
    t = time.perf_counter()
    r = asyncio.run(engine.search(query))
    dt = time.perf_counter() - t
    return {
        "time": dt,
        "prompt_tokens": r.prompt_tokens,
        "output_tokens": r.output_tokens,
        "llm_calls": r.llm_calls,
        "response_len": len(r.response) if isinstance(r.response, str) else -1,
    }


# 측정 전에 한 번 throwaway (LiteLLM connection 등 워밍)
print("\n[exp] throwaway warmup call (not measured) ...")
_throwaway = build_local_with(PROFILES["short"])
_ = run_one(_throwaway, "조선 시대 농업이란?")
print("[exp] throwaway done. starting measurements.\n")


results: dict[str, dict[str, list[dict]]] = {p: {q: [] for q in QUERIES} for p in PROFILES}

for prof_name, prof in PROFILES.items():
    print(f"\n--- profile: {prof_name}  {prof} ---")
    engine = build_local_with(prof)
    for q in QUERIES:
        for i in range(N_TRIALS):
            m = run_one(engine, q)
            results[prof_name][q].append(m)
            print(
                f"  [{prof_name}/q{QUERIES.index(q)+1}/trial {i+1}] "
                f"{m['time']:5.1f}s  prompt={m['prompt_tokens']:5d}  "
                f"out={m['output_tokens']:4d}  resp_len={m['response_len']:5d}"
            )


print("\n\n=== 요약 ===")
for q in QUERIES:
    print(f"\n질문: {q}")
    print(f"  {'profile':10s} {'mean':>7s} {'min':>7s} {'max':>7s} {'prompt_avg':>10s} {'out_avg':>8s} {'resp_avg':>9s}")
    for prof_name in PROFILES:
        rs = results[prof_name][q]
        times = [r["time"] for r in rs]
        prompts = [r["prompt_tokens"] for r in rs]
        outs = [r["output_tokens"] for r in rs]
        resps = [r["response_len"] for r in rs]
        print(
            f"  {prof_name:10s} {statistics.mean(times):6.1f}s "
            f"{min(times):6.1f}s {max(times):6.1f}s "
            f"{statistics.mean(prompts):10.0f} {statistics.mean(outs):8.0f} "
            f"{statistics.mean(resps):9.0f}"
        )

print("\n[done]")
