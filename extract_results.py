"""결과 추출: 한글 제대로 출력 + 토큰 사용량 집계."""
import json
import sys
import io
import pandas as pd
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).parent
out = ROOT / "output"

ent = pd.read_parquet(out / "entities.parquet")
rel = pd.read_parquet(out / "relationships.parquet")
com = pd.read_parquet(out / "communities.parquet")
rep = pd.read_parquet(out / "community_reports.parquet")

result = {
    "entities": int(len(ent)),
    "relationships": int(len(rel)),
    "communities_total": int(len(com)),
    "level_counts": com.groupby("level").size().to_dict(),
    "level0_titles": [],
}

# Level 0 방 이름 — community_reports에서 level==0 직접 필터
lvl0_rep = rep[rep["level"] == 0].sort_values("community")
for _, r in lvl0_rep.iterrows():
    result["level0_titles"].append({"community": int(r["community"]), "title": r["title"], "size": int(r["size"])})

# 토큰 집계 — cache 디렉터리의 LLM 응답 파일들에서 usage 추출
cache = ROOT / "cache"
total_in = 0
total_out = 0
n_calls = 0
embed_in = 0
n_embed = 0

for sub in cache.iterdir():
    if not sub.is_dir():
        continue
    for f in sub.rglob("*"):
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # graphrag 캐시 형식: {"result": ..., "input": ...} 안에 usage가 있을 수 있음
        def find_usage(obj, depth=0):
            if depth > 6 or not isinstance(obj, (dict, list)):
                return
            if isinstance(obj, dict):
                if "prompt_tokens" in obj and "completion_tokens" in obj:
                    yield ("llm", obj.get("prompt_tokens", 0), obj.get("completion_tokens", 0))
                elif "prompt_tokens" in obj and "total_tokens" in obj and "completion_tokens" not in obj:
                    # 임베딩 응답 (completion_tokens 없음)
                    yield ("embed", obj.get("prompt_tokens", 0), 0)
                for v in obj.values():
                    yield from find_usage(v, depth + 1)
            elif isinstance(obj, list):
                for v in obj:
                    yield from find_usage(v, depth + 1)

        for kind, pin, pout in find_usage(data):
            if kind == "llm":
                total_in += pin
                total_out += pout
                n_calls += 1
            else:
                embed_in += pin
                n_embed += 1

result["tokens"] = {
    "llm_calls": n_calls,
    "llm_input_tokens": total_in,
    "llm_output_tokens": total_out,
    "embed_calls": n_embed,
    "embed_input_tokens": embed_in,
}

# 비용 계산
# gpt-4.1-mini: $0.40/M 입력, $1.60/M 출력
# text-embedding-3-small: $0.02/M 입력
cost_llm_in = total_in / 1_000_000 * 0.40
cost_llm_out = total_out / 1_000_000 * 1.60
cost_embed = embed_in / 1_000_000 * 0.02
result["cost_usd"] = {
    "llm_input": round(cost_llm_in, 4),
    "llm_output": round(cost_llm_out, 4),
    "embed": round(cost_embed, 4),
    "total": round(cost_llm_in + cost_llm_out + cost_embed, 4),
}

# 단계별 시간
stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
result["timing"] = {
    "total_runtime": stats["total_runtime"],
    "extract_graph": stats["workflows"]["extract_graph"]["overall"],
    "create_communities": stats["workflows"]["create_communities"]["overall"],
    "create_community_reports": stats["workflows"]["create_community_reports"]["overall"],
    "generate_text_embeddings": stats["workflows"]["generate_text_embeddings"]["overall"],
}

print(json.dumps(result, indent=2, ensure_ascii=False))
