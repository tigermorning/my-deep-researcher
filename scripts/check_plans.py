# -*- coding: utf-8 -*-
"""① 기획 노드만 12문항 전체에 돌려 목차와 코드가 고친 건수를 본다. 기획 규칙을 바꿀 때마다 돌린다.

    PYTHONIOENCODING=utf-8 python scripts/check_plans.py          # 전체 (gpt-4o-mini 12회)
    PYTHONIOENCODING=utf-8 python scripts/check_plans.py q07 q10  # 일부
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import graph as g  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ids = sys.argv[1:] or list(g.QUESTIONS)
for qid in ids:
    q = g.QUESTIONS[qid]
    p = g.plan({"question": q["question"]})["plan"]
    fx = ", ".join(f"{k} {len(v)}" for k, v in p.items() if isinstance(v, list) and k not in ("목차", "배치") and v)
    print(f"{qid} [{q['type']}] {len(p['목차'])}절 | {fx or '고침 없음'}")
    for t in p["목차"]:
        refs = ", ".join(x for x in t["기준자료"] if x in g.META and g.META[x]["type"] == "track")
        print(f"    - {', '.join(t['시작문서'])}" + (f"  (원문 기준: {refs})" if refs else ""))
print(f"\nCOST {g.COST}")
