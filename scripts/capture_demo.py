# -*- coding: utf-8 -*-
"""README용 데모 화면 캡처. 먼저 `streamlit run app.py`를 띄워 둔다.

    python scripts/capture_demo.py q11_기본_20260923-135618_0172
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

run = sys.argv[1]
out = Path(__file__).resolve().parent.parent / "docs"
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    pg.goto(f"http://localhost:8501/?run={run}")
    pg.get_by_text("자막 규정 딥리서처").first.wait_for(timeout=30000)
    pg.wait_for_timeout(2000)
    pg.screenshot(path=str(out / "demo.png"), full_page=False)
    pg.get_by_role("tab", name="절마다 누가 무엇을").click()
    pg.get_by_text("대조 담당").first.click()
    pg.wait_for_timeout(1500)
    pg.screenshot(path=str(out / "demo_sections.png"), full_page=True)
    b.close()
print("docs/demo.png, docs/demo_sections.png")
