import requests
from bs4 import BeautifulSoup
import time

BASE_URL = "https://contents.history.go.kr/front/ta/view.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TOP_CHAPTERS = {
    "ta_m71_0060": "Ⅴ. 조선의 성립과 발전",
    "ta_m71_0070": "Ⅵ. 조선 사회의 변동",
    "ta_m71_0080": "Ⅶ. 개화와 자주 운동",
}

def fetch_page(level_id):
    resp = requests.get(BASE_URL, params={"levelId": level_id}, headers=HEADERS, timeout=10)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")

SKIP_TEXTS = {"이전", "다음", "prev", "next", "이전 페이지", "다음 페이지", ">", "<"}

def get_child_links(soup, parent_id):
    parent_depth = len(parent_id.split("_"))
    child_depth = parent_depth + 1
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "levelId=ta_m71" not in href:
            continue
        level_id = href.split("levelId=")[1].split("&")[0]
        text = a.get_text(" ", strip=True)
        if not text or text.strip() in SKIP_TEXTS:
            continue
        # 이전/다음 버튼은 class로도 걸러냄
        classes = a.get("class", [])
        if any(c in ["btn_prev", "btn_next", "prev", "next"] for c in classes):
            continue
        if len(level_id.split("_")) == child_depth and level_id.startswith(parent_id + "_"):
            if level_id not in found:
                found[level_id] = text
    return found

def get_content(soup):
    # 본문 영역 탐색
    selectors = [
        "div.text_box", "div.content_box", "div.view_cont",
        "div.cont_wrap", "div#viewContent", "div.view_content",
        "article", "div.body_cont",
    ]
    content_area = None
    for sel in selectors:
        content_area = soup.select_one(sel)
        if content_area:
            break

    if not content_area:
        # 가장 많은 <p>를 가진 div 사용
        divs = soup.find_all("div")
        content_area = max(divs, key=lambda d: len(d.find_all("p")), default=soup.body)

    paragraphs = content_area.find_all("p") if content_area else []
    texts = [p.get_text(" ", strip=True) for p in paragraphs if p.get_text(strip=True)]
    return "\n\n".join(texts)

def scrape_tree(level_id, title, depth=1):
    parts = level_id.split("_")
    current_depth = len(parts)  # ta=1, m71=2, 0060=3, 0010=4, 0010=5, 0030=6

    print(f"{'  ' * (depth-1)}[{depth}단계] {title}")
    soup = fetch_page(level_id)
    time.sleep(0.5)

    # 6단계(content page)이거나 자식 링크가 없으면 본문 추출
    children = {}
    if current_depth < 6:
        children = get_child_links(soup, level_id)

    if not children:
        content = get_content(soup)
        return {"title": title, "type": "content", "content": content}

    child_results = []
    for child_id, child_title in children.items():
        child_results.append(scrape_tree(child_id, child_title, depth + 1))

    return {"title": title, "type": "nav", "children": child_results}

def write_txt(node, f, depth=1):
    prefix = "#" * depth
    f.write(f"{prefix} {node['title']}\n\n")
    if node["type"] == "content":
        if node["content"]:
            f.write(node["content"] + "\n\n")
        f.write("---\n\n")
    else:
        for child in node.get("children", []):
            write_txt(child, f, depth + 1)

def debug_links(level_id):
    """한 페이지에서 찾은 모든 levelId 링크 출력"""
    soup = fetch_page(level_id)
    print(f"\n[DEBUG] {level_id} 페이지의 모든 ta_m71 링크:")
    for a in soup.find_all("a", href=True):
        if "levelId=ta_m71" in a["href"]:
            lid = a["href"].split("levelId=")[1].split("&")[0]
            text = a.get_text(" ", strip=True)
            print(f"  {lid!r:50s} | {text!r}")

def main():
    # 디버그: 첫 번째 대분류 페이지의 링크 확인
    debug_links("ta_m71_0060")

    output_file = "input/한국사_조선_개화기.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for level_id, title in TOP_CHAPTERS.items():
            print(f"\n=== {title} 스크래핑 시작 ===")
            result = scrape_tree(level_id, title)
            write_txt(result, f)

    print(f"\n완료: {output_file}")

if __name__ == "__main__":
    main()
