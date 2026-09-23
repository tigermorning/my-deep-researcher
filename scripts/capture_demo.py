# -*- coding: utf-8 -*-
"""README용 데모 화면 캡처. 먼저 streamlit을 띄워 둔다.

    # 지난 실행 화면 두 장(docs/demo.png · docs/demo_sections.png) — API 호출 없음
    streamlit run app.py
    python scripts/capture_demo.py q11_기본_20260923-163320_7376

    # 실행 중 진행 표시(docs/demo_progress.png) — 새 실행을 하나 돌린다(OpenAI 호출, 예시 코퍼스 s02면 약 25호출)
    DR_SAMPLE=1 streamlit run app.py --server.port 8502
    python scripts/capture_demo.py --progress s02 --port 8502

진행 캡처로 생긴 실행은 저장된다(output/sample/) — 기록을 늘리고 싶지 않으면 찍은 뒤 지운다.
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("run", nargs="?", help="지난 실행 이름(?run=으로 연다)")
ap.add_argument("--progress", metavar="질문ID", help="이 질문으로 새로 실행하며 진행 표시를 찍는다")
ap.add_argument("--port", type=int, default=8501)
a = ap.parse_args()
if not a.run and not a.progress:
    ap.error("실행 이름이나 --progress 질문ID 중 하나는 준다")

out = Path(__file__).resolve().parent.parent / "docs"
out.mkdir(exist_ok=True)
base = f"http://localhost:{a.port}"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    if a.run:
        pg.goto(f"{base}/?run={a.run}")
        pg.get_by_text("자막 규정 딥리서처").first.wait_for(timeout=30000)
        pg.wait_for_timeout(2000)
        pg.screenshot(path=str(out / "demo.png"), full_page=False)
        pg.get_by_role("tab", name="절마다 누가 무엇을").click()
        pg.get_by_text("대조 담당").first.click()
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(out / "demo_sections.png"), full_page=True)
        print("docs/demo.png, docs/demo_sections.png")
    if a.progress:
        pg.goto(base)
        side = pg.locator("[data-testid='stSidebar']")
        side.get_by_text("새로 실행").wait_for(timeout=30000)
        side.locator("[data-testid='stSelectbox']").first.click()
        pg.get_by_role("option").filter(has_text=a.progress).first.click()
        side.get_by_role("button", name="실행").click()
        # 조사관이 몇 청크 읽은 뒤(진행표가 찬 뒤)에 찍는다
        pg.get_by_text("③ 조사관 읽는 중").first.wait_for(timeout=180000)
        pg.wait_for_function("() => /읽는 중 — ([4-9]|[1-9]\\d)청크/.test(document.body.innerText)", timeout=180000)
        pg.screenshot(path=str(out / "demo_progress.png"), full_page=False)
        pg.get_by_text("끝 — 아래에서 보고서를 본다").first.wait_for(timeout=600000)
        print("docs/demo_progress.png")
    b.close()
