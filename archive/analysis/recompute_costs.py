"""
results/audit/ 의 method_sweep json 파일들 비용을 PRICING dict에 맞춰 재계산.
sweep 다시 안 돌리고 raw token 으로만 cost 채워 md/json 갱신.

단가가 추가됐을 때 (예: 5.4 시리즈) 한 번 실행하면 기존 결과들이 갱신됨.
"""

import json
import sys
from pathlib import Path

# warm_query 로딩 피하려고 PRICING/cost_for 인라인. exp_method_sweep.py 와 동기 유지.
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


ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "results" / "audit"


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


def rebuild_md(meta: dict, json_path: Path) -> str:
    model = meta["model"]
    pricing = PRICING.get(model)
    total_cost = meta["totals"].get("cost_usd")
    md_parts = [
        f"# method sweep warm: profile={meta['profile']}, model={model} ({meta['date']})",
        "",
        f"- 실행 시각: {meta['timestamp']}",
        f"- 질문: \"{meta['query']}\"",
        f"- 스냅샷: `{meta['snapshot']}`",
        f"- 프로파일: **{meta['profile']}**" + (
            " (audit 표본 2 단축판)" if meta['profile'] == "short" else " (settings.yaml 기본값)"
        ),
        f"- 모델: **{model}**" + (
            f"  (단가 ${pricing[0]}/M in, ${pricing[1]}/M out)"
            if pricing else "  (단가 미상)"
        ),
        f"- community_level: {meta['community_level']}",
        "",
        "## knobs",
        "```json",
        json.dumps(meta['knobs'], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 결과",
        "",
        md_table(meta['results']),
        "",
        f"- 합계: wall **{meta['totals']['wall_seconds']:.1f}s**" + (
            f", cost **${total_cost:.4f}**" if total_cost is not None else ", cost ?"
        ),
        "",
        "## 답 전문",
    ]
    for r in meta['results']:
        cost_str = f"${r['cost_usd']:.4f}" if r['cost_usd'] is not None else "$?"
        head = f"### {r['method']} ({r['time']:.1f}s, {cost_str})"
        body = f"> {r['response']}" if r['response'] else (
            f"(실패: {r['error']})" if r.get("error") else "(빈 답)"
        )
        md_parts += ["", head, "", body]
    return "\n".join(md_parts)


def process(json_path: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if "model" not in data:
        print(f"  [skip] {json_path.name}  (구 schema, model 키 없음)")
        return
    model = data["model"]
    pricing = PRICING.get(model)

    data["pricing"] = (
        {"input_per_M_usd": pricing[0], "output_per_M_usd": pricing[1],
         "note": "embedding 비용 제외"}
        if pricing else {"note": "단가 미상 - cost 빈칸"}
    )

    total_cost = 0.0
    have_all = True
    for r in data["results"]:
        c = cost_for(model, r.get("prompt_tokens") or 0, r.get("output_tokens") or 0)
        r["cost_usd"] = round(c, 4) if c is not None else None
        if c is not None:
            total_cost += c
        else:
            have_all = False
    data["totals"]["cost_usd"] = round(total_cost, 4) if have_all else None

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(rebuild_md(data, json_path), encoding="utf-8")
    cost_str = f"${data['totals']['cost_usd']:.4f}" if data['totals']['cost_usd'] is not None else "?"
    print(f"  [updated] {json_path.name}  model={model}  total={cost_str}")


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*method_sweep_warm*.json"
    files = sorted(AUDIT.glob(pattern))
    print(f"matched {len(files)} file(s) under {AUDIT}\n")
    for jp in files:
        process(jp)
