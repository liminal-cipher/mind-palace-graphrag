"""
results/audit/ 의 모델별 메인 sweep json/md 에 _basic_warmup 과 _drift_only 결과를 머지.
머지 후 _basic_warmup, _drift_only 파일은 삭제.
"""

import json
from pathlib import Path

from recompute_costs import rebuild_md

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "results" / "audit"
DATE = "2026-06-11"
MODELS = ["gpt-4.1-mini", "gpt-4.1", "gpt-5.4-mini", "gpt-5.4"]
SUFFIXES = ["basic_warmup", "drift_only"]
ORDER = {"basic": 0, "local": 1, "global": 2, "drift": 3}


def slug(m: str) -> str:
    return m.replace(".", "").replace("/", "_")


for model in MODELS:
    main = AUDIT / f"{DATE}_method_sweep_warm_default_{slug(model)}.json"
    if not main.exists():
        print(f"[skip] main missing: {main.name}")
        continue
    data = json.loads(main.read_text(encoding="utf-8"))

    merged = []
    extras_found = []
    for suffix in SUFFIXES:
        extra = AUDIT / f"{DATE}_method_sweep_warm_default_{slug(model)}_{suffix}.json"
        if not extra.exists():
            continue
        extras_found.append(extra)
        ed = json.loads(extra.read_text(encoding="utf-8"))
        for er in ed["results"]:
            replaced = False
            for i, r in enumerate(data["results"]):
                if r["method"] == er["method"]:
                    data["results"][i] = er
                    replaced = True
                    break
            if not replaced:
                data["results"].append(er)
            merged.append(f"{er['method']}<-{suffix}")

    data["results"].sort(key=lambda r: ORDER.get(r["method"], 99))

    total_time = sum(r["time"] for r in data["results"])
    costs = [r["cost_usd"] for r in data["results"] if r["cost_usd"] is not None]
    have_all = len(costs) == len(data["results"])
    data["totals"] = {
        "wall_seconds": round(total_time, 1),
        "cost_usd": round(sum(costs), 4) if have_all else None,
    }

    main.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md = main.with_suffix(".md")
    md.write_text(rebuild_md(data, main), encoding="utf-8")

    print(f"[merged] {model}: {merged or '(아무 extra 없음)'}")
    print(f"  saved: {main.name}, {md.name}")

    for extra in extras_found:
        emd = extra.with_suffix(".md")
        extra.unlink()
        if emd.exists():
            emd.unlink()
        print(f"  deleted: {extra.name}, {emd.name}")

print("\n[done]")
