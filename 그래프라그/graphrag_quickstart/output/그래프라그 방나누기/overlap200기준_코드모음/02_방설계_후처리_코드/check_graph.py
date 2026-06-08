import pandas as pd

ent = pd.read_parquet("output/entities.parquet")
com = pd.read_parquet("output/communities.parquet")
rep = pd.read_parquet("output/community_reports.parquet")

id2title = dict(zip(ent["id"], ent["title"]))

for _, r in com.iterrows():
    members = [id2title.get(e, e) for e in r["entity_ids"]]
    print(f"[community {r['community']} | level {r['level']} | size {r['size']}] {r['title']}")
    print("   ", ", ".join(map(str, members)))
    print()

for _, r in rep.iterrows():
    print(f"== {r['title']} ==")
    print(r["summary"])
    print()

print(ent[["title","type","degree"]].sort_values("degree", ascending=False).head(25).to_string(index=False))
