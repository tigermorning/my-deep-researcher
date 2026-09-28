# -*- coding: utf-8 -*-
"""가짜 LLM으로 그래프 전체를 돌려 HITL 승인 게이트(hitl.py)를 시험한다 — API 호출 없음.

- 예시 코퍼스(data/sample_corpus.json, 저장소에 있음)를 쓰므로 어느 PC에서나 돈다
- test_review.py와 같은 FakeLLM 대본 방식을 그대로 쓴다
- 저장 폴더(hitl.OUT)를 매 시험마다 임시 디렉터리로 바꿔치기 — 진짜 output/hitl_sample/을 안 건드린다
- 실행: python -m unittest discover -s tests -v
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["DR_SAMPLE"] = "1"                                  # graph를 불러오기 전에 정해야 함
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")          # graph가 불러올 때 키가 있는지만 본다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import graph as g   # noqa: E402
import hitl          # noqa: E402

SDH_KO = "달빛 우체국 E01 한국어 SDH"
SDH_EN = "등대지기의 겨울 E03 영어 SDH"
RULE_KO = "예시플릭스 한국어 가이드 II. SDH"
RULE_EN = "예시플릭스 영어 가이드"
QUESTION = g.QUESTIONS["s02"]["question"]
A, B = "달빛 우체국 SDH 표기", "등대지기의 겨울 SDH 표기"


def draft(n_cites, doc):
    return " ".join(f"화자 표기 사례 {i + 1}을 정리했다(«{doc}»)." for i in range(n_cites))


class FakeLLM:
    """test_review.py의 FakeLLM과 같은 대본 방식(절 이름 → 바퀴마다 집필 결과 목록)."""

    def __init__(self, script):
        self.script = script
        self.writes = {A: 0, B: 0}
        self.calls = 0

    def __call__(self, prompt, who, as_json=False, temperature=0):
        self.calls += 1
        with g._cost_lock:
            g.COST["calls"] += 1
            g.COST[f"{who}_chars"] += len(prompt)
        if '"목차"' in prompt:
            return {"목차": [
                {"절": A, "역할": "관행 담당", "시작문서": [SDH_KO], "기준자료": [RULE_KO], "지시": "화자·효과음 표기를 모은다"},
                {"절": B, "역할": "관행 담당", "시작문서": [SDH_EN], "기준자료": [RULE_EN], "지시": "화자·효과음 표기를 모은다"}]}
        if '"원고"' in prompt and '"충분"' in prompt:
            hit = [n for n in (A, B) if n in prompt]
            assert len(hit) == 1, f"집필 프롬프트에서 절을 못 가림: {hit}"
            sec = hit[0]
            steps = self.script[sec]
            out = steps[min(self.writes[sec], len(steps) - 1)]
            self.writes[sec] += 1
            return dict(out)
        if '"제목"' in prompt and '"맺음말"' in prompt:
            return {"제목": "시험 보고서", "머리말": "머리말.", "맺음말": "맺음말."}
        if as_json:
            return {}
        return "화자 이름은 대괄호로 적혀 있다."


class HitlGateTest(unittest.TestCase):
    def setUp(self):
        self._conf = copy.deepcopy(g.설정)
        self._ask, self._client = g.ask, g._client
        g._client = None
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_out = hitl.OUT
        hitl.OUT = Path(self._tmp.name)
        hitl._stack.close()
        import contextlib
        hitl._stack = contextlib.ExitStack()
        hitl._saver = None

    def tearDown(self):
        g.설정.clear()
        g.설정.update(self._conf)
        g.ask, g._client = self._ask, self._client
        hitl._stack.close()
        hitl.OUT = self._orig_out
        hitl._saver = None
        self._tmp.cleanup()

    def start(self, script, qid="test", **switch):
        g.설정["스위치"].update(switch)
        g.ask = FakeLLM(script)
        return hitl.start(QUESTION, qid)

    def test_clean_run_auto_passes_and_saves(self):
        """경보 없고 부족 신고도 없으면 사람을 거치지 않고 그대로 저장된다."""
        r = self.start({A: [{"원고": draft(2, SDH_KO), "충분": True, "부족": ""}],
                        B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        self.assertFalse(r["pending"])
        self.assertIsNotNone(r["run"])
        self.assertEqual(r["out"]["plan"]["승인기록"]["결정"], "자동통과")
        self.assertTrue((hitl.OUT / "reports" / f"{r['run']}.md").exists())
        rows = hitl.saved_runs()
        self.assertEqual(rows[r["run"]]["decision"], "자동통과")

    def test_round_cap_interrupts_then_approve_saves(self):
        """바퀴 소진 + 부족 신고 → 미흡 위험으로 멈춘다. 승인하면 그제서야 저장된다."""
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "효과음 사례가 부족하다"}
        r = self.start({A: [short], B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        self.assertTrue(r["pending"])
        self.assertIsNone(r["run"])
        p = hitl.peek(r["thread_id"])
        self.assertTrue(p["pending"])
        self.assertIn("미흡 위험", p["payload"]["멈춘 이유"][0])
        self.assertFalse((hitl.OUT / "reports").exists())   # 승인 전엔 아무것도 안 나간다
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "승인"})
        self.assertFalse(r2["pending"])
        self.assertIsNotNone(r2["run"])
        self.assertTrue((hitl.OUT / "reports" / f"{r2['run']}.md").exists())
        self.assertEqual(r2["out"]["plan"]["승인기록"]["결정"], "승인")

    def test_reject_does_not_publish_report(self):
        """반려하면 감사 기록(runs/*.json)은 남지만 output/hitl*/reports/에는 안 올라간다."""
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "효과음 사례가 부족하다"}
        r = self.start({A: [short], B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        self.assertTrue(r["pending"])
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "반려", "사유": "인용을 원문과 다시 대조해야 함"})
        self.assertFalse(r2["pending"])
        self.assertIsNotNone(r2["run"])
        self.assertFalse((hitl.OUT / "reports").exists())
        row = hitl.saved_runs()[r2["run"]]
        self.assertEqual(row["decision"], "반려")
        self.assertEqual(row["승인기록"]["사유"], "인용을 원문과 다시 대조해야 함")

    def test_edited_report_is_what_gets_saved(self):
        """수정 후 승인이면 담당자가 고친 본문이 저장된다(원래 초안이 아니라)."""
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "효과음 사례가 부족하다"}
        r = self.start({A: [short], B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        edited = "# 고친 보고서\n\n담당자가 손으로 고친 본문."
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "수정후승인", "수정본": edited})
        saved = (hitl.OUT / "reports" / f"{r2['run']}.md").read_text(encoding="utf-8")
        self.assertEqual(saved, edited)

    def test_pending_threads_lists_only_unresolved(self):
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "효과음 사례가 부족하다"}
        r1 = self.start({A: [short], B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]}, qid="pend1")
        r2 = self.start({A: [{"원고": draft(2, SDH_KO), "충분": True, "부족": ""}],
                          B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]}, qid="pend2")
        pend = {e["thread_id"] for e in hitl.pending_threads()}
        self.assertIn(r1["thread_id"], pend)
        self.assertNotIn(r2["thread_id"], pend)


if __name__ == "__main__":
    unittest.main(verbosity=2)
