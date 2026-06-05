import pandas as pd
from openai import AzureOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2025-01-01-preview"
)

base = "output/그래프라그 방나누기/gpt4.1mini/2차"
c = pd.read_parquet(f"{base}/communities.parquet")
cr = pd.read_parquet(f"{base}/community_reports.parquet")
titles = dict(zip(cr["community"], cr["title"]))
level0 = c[c["level"] == 0]

lines = []
for i, (_, row) in enumerate(level0.iterrows()):
    cid = row["community"]
    original = titles.get(cid, "?")

    response = client.chat.completions.create(
        model="gpt-4.1-mini_Chosun_Test",
        messages=[
            {"role": "system", "content": "다음 제목을 자연스러운 한국어로 번역해줘. 제목만 출력하고 다른 말은 하지 마."},
            {"role": "user", "content": original}
        ],
        max_completion_tokens=100
    )
    korean = response.choices[0].message.content.strip()
    lines.append(f"방 {i+1}: {korean}")
    print(f"방 {i+1}: {korean}")

with open(f"{base}/방제목_한국어.txt", "w", encoding="utf-8-sig") as f:
    f.write("\n".join(lines))

print("\n저장 완료: 방제목_한국어.txt")
