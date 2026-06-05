import pandas as pd

base = "output/그래프라그 방나누기/gpt4.1mini/2차"
c = pd.read_parquet(f"{base}/communities.parquet")
cr = pd.read_parquet(f"{base}/community_reports.parquet")
titles = dict(zip(cr["community"], cr["title"]))
level0 = c[c["level"] == 0]

for i, (_, row) in enumerate(level0.iterrows()):
    print(f"방 {i+1}: {titles.get(row['community'], '?')}")
