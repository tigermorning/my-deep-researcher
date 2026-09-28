# -*- coding: utf-8 -*-
"""README·REPORT.md 12절용 HITL 데모 화면 캡처. 먼저 hitl_app.py를 띄워 둔다.

    streamlit run hitl_app.py --server.port 8503
    python scripts/capture_hitl_demo.py --question q10 --port 8503

새 실행을 하나 돌려(실제 코퍼스·API 호출) 승인 대기 화면을 찍고, 승인 버튼을 눌러 완료된 실행
화면도 찍는다. docs/hitl_demo_pending.png · docs/hitl_demo_done.png
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--question", required=True, help="질문 id(q01 등)")
ap.add_argument("--port", type=int, default=8503)
a = ap.parse_args()

out = Path(__file__).resolve().parent.parent / "docs"
out.mkdir(exist_ok=True)
base = f"http://localhost:{a.port}"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1400})
    pg.goto(base)
    side = pg.locator("[data-testid='stSidebar']")
    side.get_by_text("새 조사 시작").wait_for(timeout=30000)
    side.locator("[data-testid='stSelectbox']").first.click()
    pg.get_by_role("option").filter(has_text=a.question).first.click()
    side.get_by_role("button", name="실행").click()
    pg.get_by_text("승인 대기로 넘어감").first.wait_for(timeout=300000)
    pg.get_by_role("tab", name="승인 대기").click()
    pg.get_by_text("멈춘 이유").first.wait_for(timeout=10000)
    pg.wait_for_timeout(1000)
    pg.screenshot(path=str(out / "hitl_demo_pending.png"), full_page=True)
    print("docs/hitl_demo_pending.png")

    pg.get_by_role("radio").first.check()
    pg.get_by_role("button", name="제출").click()
    pg.get_by_text("대기 중인 건이 없다").first.wait_for(timeout=15000)
    pg.get_by_role("tab", name="완료된 실행").click()
    pg.get_by_text("실행 기록").first.wait_for(timeout=10000)
    pg.wait_for_timeout(1000)
    pg.screenshot(path=str(out / "hitl_demo_done.png"), full_page=False)
    print("docs/hitl_demo_done.png")
    b.close()
