from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/11차_최종방_엔티티분류_repaired_no_llm.json"
)
FALLBACK_INPUT = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/11차_최종방_엔티티분류.json"
)
DEFAULT_OUTPUT = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/11차_방_엔티티_시각화.html"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static room/entity visualization.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_payload(path: Path) -> tuple[dict[str, Any], Path]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), path
    return json.loads(FALLBACK_INPUT.read_text(encoding="utf-8")), FALLBACK_INPUT


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def entity_list(room: dict[str, Any], level: str) -> list[dict[str, Any]]:
    return [
        entity
        for entity in room.get("entities", [])
        if entity.get("visibility") == level
    ]


def render_entity(entity: dict[str, Any]) -> str:
    score = entity.get("score", "")
    kind = entity.get("type", "")
    reason = entity.get("llm_reason") or entity.get("auto_core_reason") or ""
    low = " low-confidence" if entity.get("low_confidence_core") else ""
    return f"""
      <li class="entity{low}" data-entity-title="{esc(entity.get('title', ''))}">
        <button class="entity-main" type="button">
          <span class="entity-title">{esc(entity.get('title', ''))}</span>
          <span class="entity-meta">{esc(kind)} · {esc(score)}</span>
        </button>
        <p class="entity-desc">{esc(entity.get('description', ''))}</p>
        {f'<p class="entity-reason">{esc(reason)}</p>' if reason else ''}
      </li>
    """


def render_room(room: dict[str, Any]) -> str:
    summaries = room.get("visibility_summary", {})
    subzones = "\n".join(
        f"""
        <li>
          <span>{esc(subzone.get('title', ''))}</span>
          <code>{esc(subzone.get('source_communities', []))}</code>
        </li>
        """
        for subzone in room.get("subzones", [])
    )
    sections = []
    for level, label in [
        ("core", "Core"),
        ("supporting", "Supporting"),
        ("search_only", "Search Only"),
    ]:
        entities = entity_list(room, level)
        sections.append(
            f"""
            <section class="entity-section {level}">
              <button class="section-title" type="button" data-toggle="{esc(level)}">
                <span>{label}</span>
                <strong>{len(entities)}</strong>
              </button>
              <ul class="entities">
                {''.join(render_entity(entity) for entity in entities)}
              </ul>
            </section>
            """
        )
    return f"""
    <article class="room" data-room-title="{esc(room.get('title', ''))}">
      <header class="room-head">
        <div>
          <p class="room-no">Room {esc(room.get('room_no', ''))}</p>
          <h2>{esc(room.get('title', ''))}</h2>
        </div>
        <div class="room-stats">
          <span>{esc(room.get('entity_count', 0))} entities</span>
          <span>{len(room.get('source_communities', []))} communities</span>
        </div>
      </header>
      <p class="flow">{esc(room.get('learning_flow', ''))}</p>
      <div class="badges">
        <span class="badge core-b">core {esc(summaries.get('core', 0))}</span>
        <span class="badge support-b">supporting {esc(summaries.get('supporting', 0))}</span>
        <span class="badge search-b">search {esc(summaries.get('search_only', 0))}</span>
      </div>
      <details class="subzones" open>
        <summary>Subzones and Source Communities</summary>
        <ul>{subzones}</ul>
      </details>
      <div class="entity-grid">
        {''.join(sections)}
      </div>
    </article>
    """


def render_html(payload: dict[str, Any], source_path: Path) -> str:
    rooms = payload.get("rooms", [])
    validation = payload.get("room_validation") or payload.get("no_llm_repair_validation_after", {})
    repair_actions = payload.get("room_repair_report", {}).get("actions", [])
    if "no_llm_repair_actions" in payload:
        repair_actions = payload["no_llm_repair_actions"]
    quality_patch = payload.get("quality_patch", {})
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>11차 방/엔티티 시각화</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f2328;
      --muted: #667085;
      --line: #d9dee7;
      --paper: #fbfcfe;
      --panel: #ffffff;
      --green: #1b7f4c;
      --blue: #2266aa;
      --amber: #a15c05;
      --red: #b42318;
      --violet: #6b3fb3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", system-ui, sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    .app-header {{
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 254, 0.96);
      backdrop-filter: blur(8px);
    }}
    .topbar {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 24px 12px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 24px;
      font-weight: 750;
      letter-spacing: 0;
    }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(240px, 1fr) auto auto auto;
      gap: 10px;
      align-items: center;
    }}
    input, select, button {{
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }}
    input {{ padding: 0 12px; }}
    select, button {{ padding: 0 10px; }}
    button {{ cursor: pointer; }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 24px 40px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .metric strong {{
      display: block;
      margin-top: 4px;
      font-size: 20px;
    }}
    .notice {{
      border: 1px solid #efc16b;
      background: #fff8e8;
      color: #6f4300;
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 18px;
      font-size: 14px;
    }}
    .rooms {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }}
    .room {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 16px;
    }}
    .room-head {{
      display: flex;
      gap: 16px;
      align-items: flex-start;
      justify-content: space-between;
      border-bottom: 1px solid var(--line);
      padding-bottom: 12px;
    }}
    .room-no {{
      margin: 0 0 4px;
      color: var(--violet);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.32;
      letter-spacing: 0;
    }}
    .room-stats {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
    }}
    .room-stats span, .badge {{
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 5px 9px;
      background: #fff;
      font-size: 12px;
      white-space: nowrap;
    }}
    .flow {{
      margin: 12px 0;
      color: #384152;
      line-height: 1.58;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .core-b {{ color: var(--green); border-color: #a9d7bd; }}
    .support-b {{ color: var(--blue); border-color: #abcceb; }}
    .search-b {{ color: var(--amber); border-color: #e7c48c; }}
    .subzones {{
      margin: 8px 0 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: #fcfdff;
    }}
    summary {{ cursor: pointer; font-weight: 700; }}
    .subzones ul {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 8px;
      margin: 10px 0 0;
      padding: 0;
      list-style: none;
    }}
    .subzones li {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fff;
      min-width: 0;
    }}
    .subzones code {{ color: var(--muted); white-space: nowrap; }}
    .entity-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }}
    .entity-section {{
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
    }}
    .section-title {{
      width: 100%;
      display: flex;
      justify-content: space-between;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      padding: 10px 12px;
      font-weight: 700;
      background: #f7f9fc;
    }}
    .entities {{
      list-style: none;
      margin: 0;
      padding: 0;
      max-height: 380px;
      overflow: auto;
    }}
    .entity {{
      border-bottom: 1px solid #eef1f6;
    }}
    .entity:last-child {{ border-bottom: 0; }}
    .entity-main {{
      width: 100%;
      display: flex;
      gap: 8px;
      justify-content: space-between;
      align-items: center;
      border: 0;
      border-radius: 0;
      padding: 9px 10px;
      text-align: left;
      background: #fff;
    }}
    .entity-main:hover {{ background: #f7f9fc; }}
    .entity-title {{
      font-weight: 650;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .entity-meta {{
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 12px;
    }}
    .entity-desc, .entity-reason {{
      display: none;
      margin: 0;
      padding: 0 10px 10px;
      color: #4c5566;
      line-height: 1.5;
      font-size: 13px;
    }}
    .entity.open .entity-desc, .entity.open .entity-reason {{ display: block; }}
    .entity-reason {{ color: var(--blue); }}
    .low-confidence .entity-title::after {{
      content: " low";
      margin-left: 5px;
      color: var(--red);
      font-size: 11px;
      font-weight: 700;
    }}
    .hidden {{ display: none !important; }}
    @media (max-width: 980px) {{
      .controls {{ grid-template-columns: 1fr 1fr; }}
      .summary {{ grid-template-columns: repeat(2, 1fr); }}
      .entity-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      .topbar, main {{ padding-left: 14px; padding-right: 14px; }}
      .controls, .summary {{ grid-template-columns: 1fr; }}
      .room-head {{ flex-direction: column; }}
      .room-stats {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <header class="app-header">
    <div class="topbar">
      <h1>11차 방/엔티티 시각화</h1>
      <div class="controls">
        <input id="search" type="search" placeholder="방 제목, 엔티티, 설명 검색" />
        <select id="level">
          <option value="all">전체 엔티티</option>
          <option value="core">Core만</option>
          <option value="supporting">Supporting만</option>
          <option value="search_only">Search Only만</option>
        </select>
        <button id="expand" type="button">설명 펼치기</button>
        <button id="collapse" type="button">설명 접기</button>
      </div>
    </div>
  </header>
  <main>
    <section class="summary">
      <div class="metric"><span>rooms</span><strong>{len(rooms)}</strong></div>
      <div class="metric"><span>validation</span><strong>{esc(validation.get('valid', 'n/a'))}</strong></div>
      <div class="metric"><span>repair actions</span><strong>{len(repair_actions)}</strong></div>
      <div class="metric"><span>source</span><strong>{esc(source_path.name)}</strong></div>
    </section>
    <div class="notice">
      Quality patch: {esc(quality_patch)}<br />
      Validation: {esc(validation)}
    </div>
    <section class="rooms">
      {''.join(render_room(room) for room in rooms)}
    </section>
  </main>
  <script>
    const search = document.getElementById('search');
    const level = document.getElementById('level');
    const applyFilters = () => {{
      const q = search.value.trim().toLowerCase();
      const selected = level.value;
      document.querySelectorAll('.room').forEach(room => {{
        let roomMatch = room.dataset.roomTitle.toLowerCase().includes(q);
        let anyEntity = false;
        room.querySelectorAll('.entity-section').forEach(section => {{
          const sectionLevel = section.classList.contains('core') ? 'core' :
            section.classList.contains('supporting') ? 'supporting' : 'search_only';
          const sectionAllowed = selected === 'all' || selected === sectionLevel;
          section.classList.toggle('hidden', !sectionAllowed);
          section.querySelectorAll('.entity').forEach(entity => {{
            const text = entity.textContent.toLowerCase();
            const match = !q || text.includes(q) || roomMatch;
            entity.classList.toggle('hidden', !match);
            anyEntity = anyEntity || (sectionAllowed && match);
          }});
        }});
        room.classList.toggle('hidden', q && !roomMatch && !anyEntity);
      }});
    }};
    search.addEventListener('input', applyFilters);
    level.addEventListener('change', applyFilters);
    document.querySelectorAll('.entity-main').forEach(button => {{
      button.addEventListener('click', () => button.closest('.entity').classList.toggle('open'));
    }});
    document.getElementById('expand').addEventListener('click', () => {{
      document.querySelectorAll('.entity').forEach(entity => entity.classList.add('open'));
    }});
    document.getElementById('collapse').addEventListener('click', () => {{
      document.querySelectorAll('.entity').forEach(entity => entity.classList.remove('open'));
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    payload, source_path = load_payload(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(payload, source_path), encoding="utf-8")
    print(f"Wrote: {args.output}")
    print(f"Source: {source_path}")


if __name__ == "__main__":
    main()
