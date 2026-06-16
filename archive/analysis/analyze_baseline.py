"""Baseline 결과 분석: entities/relationships/communities (level별) + 토큰/비용."""
import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
out = ROOT / "output"

ent = pd.read_parquet(out / "entities.parquet")
rel = pd.read_parquet(out / "relationships.parquet")
com = pd.read_parquet(out / "communities.parquet")
rep = pd.read_parquet(out / "community_reports.parquet")

print("=== ENTITIES ===")
print(f"수: {len(ent)}")
print(f"컬럼: {list(ent.columns)}")
print(ent.head(3))

print("\n=== RELATIONSHIPS ===")
print(f"수: {len(rel)}")

print("\n=== COMMUNITIES ===")
print(f"전체 수: {len(com)}")
print(f"컬럼: {list(com.columns)}")
lvl_counts = com.groupby("level").size().sort_index()
print("Level별 개수:")
print(lvl_counts.to_string())

print("\n=== COMMUNITY_REPORTS ===")
print(f"수: {len(rep)}")
print(f"컬럼: {list(rep.columns)}")

# Level 0 방 이름
print("\n=== LEVEL 0 방 이름 (community_reports에서 title 추출) ===")
lvl0_ids = com[com["level"] == 0]["community"].tolist() if "community" in com.columns else com[com["level"] == 0].index.tolist()
print(f"Level 0 community IDs: {lvl0_ids}")
title_col = "title" if "title" in rep.columns else ("name" if "name" in rep.columns else None)
id_col = "community" if "community" in rep.columns else "id"
if title_col:
    lvl0_reports = rep[rep[id_col].isin(lvl0_ids)] if id_col in rep.columns else rep[rep["level"] == 0]
    for _, r in lvl0_reports.iterrows():
        cid = r.get(id_col, r.get("id", "?"))
        print(f"  - [community {cid}] {r[title_col]}")

# Stats
print("\n=== STATS.JSON ===")
stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
print(json.dumps(stats, indent=2, ensure_ascii=False))
