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

base = "output/그래프라그 방나누기/gpt4.1mini/10차_프롬프트/10차(수정)"
output_file = f"{base}/방별내용.txt"

entities = pd.read_parquet(f"{base}/entities.parquet")
relationships = pd.read_parquet(f"{base}/relationships.parquet")
communities = pd.read_parquet(f"{base}/communities.parquet")
reports = pd.read_parquet(f"{base}/community_reports.parquet")

report_titles = dict(zip(reports["community"], reports["title"]))
level0 = communities[communities["level"] == 0]

def translate(text):
    res = client.chat.completions.create(
        model="gpt-4.1-mini_Chosun_Test",
        messages=[
            {"role": "system", "content": "다음 제목을 자연스러운 한국어로 번역해줘. 이미 한국어면 그대로 반환해. 제목만 출력하고 다른 말은 하지 마."},
            {"role": "user", "content": text}
        ],
        max_completion_tokens=100
    )
    return res.choices[0].message.content.strip()

lines = []
# 설정 정보
entity_types_str = "인물, 사건, 정책, 문물, 기관"
max_cluster_size = 80
use_lcc = False
temperature = 0.0

lines.append("=" * 60)
lines.append("【 10차(수정) 결과 】")
lines.append(f"설정: entity_types=[{entity_types_str}], max_cluster_size={max_cluster_size}, use_lcc={use_lcc}, temperature={temperature}, prompts=history_learning_type_name_fix")
lines.append("=" * 60)
lines.append(f"엔티티 수: {len(entities)}개")
lines.append(f"관계 수: {len(relationships)}개")
lines.append(f"전체 커뮤니티 수: {len(communities)}개")
for lvl, cnt in communities['level'].value_counts().sort_index().items():
    lines.append(f"  level_{lvl}: {cnt}개")
lines.append(f"현재 사용 레벨: level_0 ({len(level0)}개 방)")
lines.append("")

for i, (_, room) in enumerate(level0.iterrows()):
    cid = room["community"]
    entity_ids = list(room["entity_ids"])
    title = report_titles.get(cid, f"Community {cid}")
    korean_title = translate(title)
    print(f"방 {i+1}: {korean_title}")

    lines.append("=" * 60)
    lines.append(f"방 {i+1}: {korean_title}")
    lines.append("-" * 60)

    members = entities[entities["id"].isin(entity_ids)]
    for _, ent in members.iterrows():
        name = ent.get("title") or "?"
        etype = ent.get("type", "")
        desc = str(ent.get("description", ""))[:60]
        lines.append(f"  [{etype}] {name} - {desc}")
    lines.append("")

with open(output_file, "w", encoding="utf-8-sig") as f:
    f.write("\n".join(lines))

print(f"\n저장 완료: {output_file}")
