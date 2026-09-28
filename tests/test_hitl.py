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
    """test_review.py의 FakeLLM과 같은 대본 방식(절 이름 → 바퀴마다 집필 결과 목록).
    bad_ref=True면 목차에 코퍼스에 없는 제목을 하나 끼워 배정검사가 '무효배정'으로 잡게 한다
    (기획 게이트 시험용) — 담당자 지시(재기획 마크)가 붙어도 대본은 그대로 안 바뀐다(모델이
    실제로 지시를 반영하는지는 이 가짜로는 확인 못 함 — 재기획 상한만 시험한다)."""

    def __init__(self, script, bad_ref=False):
        self.script = script
        self.bad_ref = bad_ref
        self.writes = {A: 0, B: 0}
        self.calls = 0

    def __call__(self, prompt, who, as_json=False, temperature=0):
        self.calls += 1
        with g._cost_lock:
            g.COST["calls"] += 1
            g.COST[f"{who}_chars"] += len(prompt)
        if '"목차"' in prompt:
            refs_a = [RULE_KO, "없는 문서"] if self.bad_ref else [RULE_KO]
            return {"목차": [
                {"절": A, "역할": "관행 담당", "시작문서": [SDH_KO], "기준자료": refs_a, "지시": "화자·효과음 표기를 모은다"},
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

    def start(self, script, qid="test", bad_ref=False, **switch):
        g.설정["스위치"].update(switch)
        g.ask = FakeLLM(script, bad_ref=bad_ref)
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

    # ---------------------------------------------------------------- ◐ 기획 게이트
    CLEAN_SCRIPT = {A: [{"원고": draft(2, SDH_KO), "충분": True, "부족": ""}],
                     B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]}

    def test_plan_gate_auto_passes_when_clean(self):
        """배정검사가 고칠 게 없으면 기획 게이트도 사람을 안 거친다."""
        r = self.start(self.CLEAN_SCRIPT)
        self.assertFalse(r["pending"])
        self.assertEqual(r["out"]["plan"]["기획승인기록"]["결정"], "자동통과")

    def test_plan_gate_interrupts_on_bad_ref(self):
        """목차에 코퍼스에 없는 제목이 섞이면(무효배정) 조사 시작 전에 멈춘다."""
        r = self.start(self.CLEAN_SCRIPT, bad_ref=True)
        self.assertTrue(r["pending"])
        payload = hitl.peek(r["thread_id"])["payload"]
        self.assertEqual(payload["종류"], "기획")
        self.assertIn("없는 문서", " ".join(payload["근거"]))
        self.assertIn("목차", payload)

    def test_plan_gate_approve_lets_research_continue(self):
        """승인하면 그 목차로 조사가 이어지고, 문제 없으면 끝까지 가서 저장된다."""
        r = self.start(self.CLEAN_SCRIPT, bad_ref=True)
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "승인"})
        self.assertFalse(r2["pending"])
        self.assertEqual(r2["out"]["plan"]["기획승인기록"]["결정"], "승인")
        self.assertIsNotNone(r2["run"])
        self.assertTrue((hitl.OUT / "reports" / f"{r2['run']}.md").exists())

    def test_plan_gate_reject_stops_before_research(self):
        """기획 게이트에서 반려하면 조사(청크 읽기) 자체가 시작 안 된다 — LLM 호출이 안 늘어난다."""
        r = self.start(self.CLEAN_SCRIPT, bad_ref=True)
        calls_at_pause = g.ask.calls
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "반려", "사유": "«없는 문서»는 실재하지 않는다"})
        self.assertFalse(r2["pending"])
        self.assertEqual(g.ask.calls, calls_at_pause, "반려 후엔 추가 LLM 호출(조사)이 없어야 한다")
        row = hitl.saved_runs()[r2["run"]]
        self.assertEqual(row["decision"], "기획반려")
        self.assertEqual(row["metrics"], {})
        self.assertNotIn("report_file", row)
        self.assertFalse((hitl.OUT / "reports").exists())

    def test_plan_gate_edit_overrides_section_instruction(self):
        """수정 후 승인이면 담당자가 고친 절별 지시문이 실제로 반영된다."""
        r = self.start(self.CLEAN_SCRIPT, bad_ref=True)
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "수정후승인", "수정본": {A: "고친 지시문"}})
        self.assertFalse(r2["pending"])
        sec = next(t for t in r2["out"]["plan"]["목차"] if t["절"] == A)
        self.assertEqual(sec["지시"], "고친 지시문")

    def test_plan_gate_replan_cap_then_proceeds(self):
        """같은 무효배정이 재기획 뒤에도 남으면 한 번만 되돌리고, 그다음은 상한에 걸려 그대로 진행한다
        (가짜 LLM은 지시를 실제로 반영 못 하므로 두 번째도 같은 무효배정이 남는 걸 확인하는 시험)."""
        r = self.start(self.CLEAN_SCRIPT, bad_ref=True)
        self.assertTrue(r["pending"])
        r2 = hitl.resume(r["thread_id"], "test", {"결정": "다시판정", "지시": "«없는 문서» 빼고 다시 짜라"})
        self.assertTrue(r2["pending"], "재기획해도 같은 무효배정이 남아 다시 멈춰야 한다")
        self.assertEqual(hitl.peek(r["thread_id"])["payload"]["종류"], "기획")
        r3 = hitl.resume(r["thread_id"], "test", {"결정": "다시판정", "지시": "그래도 빼라"})
        self.assertFalse(r3["pending"], "재기획 상한을 넘으면 다시판정 요청도 그대로 진행돼야 한다")
        self.assertEqual(r3["out"]["plan"]["기획승인기록"]["결정"], "승인")
        self.assertIn("상한", r3["out"]["plan"]["기획승인기록"]["사유"])
        self.assertIsNotNone(r3["run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
