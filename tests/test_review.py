# -*- coding: utf-8 -*-
"""가짜 LLM으로 그래프 전체를 돌려 ④ 점검(재위임·채택 규칙)을 시험한다 — API 호출 없음.

- 예시 코퍼스(data/sample_corpus.json, 저장소에 있음)를 쓰므로 어느 PC에서나 돈다
- graph.ask를 대본대로 답하는 가짜로 바꾸고, 진짜 OpenAI 클라이언트는 부르면 바로 실패하게 막는다
- 실행: python -m unittest discover -s tests -v
"""
import copy
import os
import re
import sys
import unittest
from pathlib import Path

os.environ["DR_SAMPLE"] = "1"                                  # graph를 불러오기 전에 정해야 함
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")          # graph가 불러올 때 키가 있는지만 본다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import graph as g  # noqa: E402

SDH_KO = "달빛 우체국 E01 한국어 SDH"
SDH_EN = "등대지기의 겨울 E03 영어 SDH"
RULE_KO = "예시플릭스 한국어 가이드 II. SDH"
RULE_EN = "예시플릭스 영어 가이드"
QUESTION = g.QUESTIONS["s02"]["question"]
A, B = "달빛 우체국 SDH 표기", "등대지기의 겨울 SDH 표기"


def draft(n_cites, doc):
    """유효 인용 n개짜리 원고. 인용은 그 절이 첫 청크로 반드시 읽는 시작문서에만 붙인다(허위인용이 안 나게)."""
    return " ".join(f"화자 표기 사례 {i + 1}을 정리했다(«{doc}»)." for i in range(n_cites))


class FakeLLM:
    """프롬프트 모양으로 어느 호출인지 가려 대본대로 답한다.
    script[절 이름] = 바퀴마다 집필 결과 목록(마지막 것을 이후 바퀴에도 씀)."""

    def __init__(self, script):
        self.script = script
        self.writes = {A: 0, B: 0}
        self.calls = 0

    def __call__(self, prompt, who, as_json=False, temperature=0):
        self.calls += 1
        with g._cost_lock:                          # 진짜 ask처럼 센다 — 격리율 지표가 이 값을 쓴다
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
            return {}                               # 다음 청크 고르기 등 — 빈 답이면 코드가 첫 후보를 쓴다
        return "화자 이름은 대괄호로 적혀 있다."        # 메모(큐 번호 없음 → 메모 대조 되물음 없음)


class ReviewLoopTest(unittest.TestCase):
    def setUp(self):
        self._conf = copy.deepcopy(g.설정)
        self._ask, self._client = g.ask, g._client
        g._client = None                            # 가짜를 거치지 않은 호출이 있으면 AttributeError로 드러남

    def tearDown(self):
        g.설정.clear()
        g.설정.update(self._conf)
        g.ask, g._client = self._ask, self._client

    def run_graph(self, script, **switch):
        g.설정["스위치"].update(switch)
        fake = FakeLLM(script)
        g.ask = fake
        out = g.run(QUESTION, "test", "시험", quiet=True, keep=False)   # keep=False: output/에 저장하지 않음
        return out, fake

    def adopted(self, out):
        return {v["절"]: v for v in out["plan"]["채택"].values()}

    def rounds_read(self, out, name):
        i = next(v["번호"] for v in self.adopted(out).values() if v["절"] == name)
        return sorted({r for j, _, r in out["visited"] if j == i})

    def test_fewer_cites_keeps_old_draft(self):
        """재작성본의 유효 인용이 줄면 지난 원고를 지킨다(되돌림) — 이번 바퀴에 읽은 청크는 넘겨받는다."""
        first = {"원고": draft(2, SDH_KO), "충분": False, "부족": "효과음 사례가 부족하다"}
        out, fake = self.run_graph({A: [first, {"원고": draft(1, SDH_KO), "충분": True, "부족": ""}],
                                    B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        p, sec = out["plan"], self.adopted(out)[A]
        self.assertEqual(p["재위임기록"], [A])
        self.assertEqual(p["되돌림"], [A])
        self.assertEqual(sec["원고"], first["원고"])
        self.assertEqual(self.rounds_read(out, A), [1, 2])
        read_r2 = {c for j, c, r in out["visited"] if j == sec["번호"] and r == 2}
        self.assertTrue(read_r2 and read_r2 <= set(sec["읽은청크"]), "2바퀴에 읽은 청크를 넘겨받아야 함")
        self.assertIn(first["원고"], out["report"])
        self.assertEqual(fake.writes, {A: 2, B: 1})

    def test_empty_rewrite_keeps_old_draft(self):
        first = {"원고": draft(1, SDH_KO), "충분": False, "부족": "사례가 부족하다"}
        out, _ = self.run_graph({A: [first, {"원고": "", "충분": True, "부족": ""}],
                                 B: [{"원고": draft(1, SDH_EN), "충분": True, "부족": ""}]})
        self.assertEqual(out["plan"]["되돌림"], [A])
        self.assertEqual(self.adopted(out)[A]["원고"], first["원고"])

    def test_more_cites_adopts_rewrite(self):
        second = {"원고": draft(3, SDH_KO), "충분": True, "부족": ""}
        out, _ = self.run_graph({A: [{"원고": draft(1, SDH_KO), "충분": False, "부족": "사례가 부족하다"}, second],
                                 B: [{"원고": draft(1, SDH_EN), "충분": True, "부족": ""}]})
        self.assertEqual(out["plan"]["되돌림"], [])
        self.assertEqual(self.adopted(out)[A]["원고"], second["원고"])
        self.assertEqual(out["plan"]["종료"], "빈 칸 없음")

    def test_round_cap_stops_loop(self):
        """계속 부족하다고 신고해도 최대바퀴에서 멈춘다."""
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "사례가 부족하다"}
        out, fake = self.run_graph({A: [short], B: [{"원고": draft(1, SDH_EN), "충분": True, "부족": ""}]})
        cap = g.설정["최대바퀴"]
        self.assertEqual(out["plan"]["재위임기록"], [A] * (cap - 1))
        self.assertEqual(out["plan"]["종료"], "바퀴 소진")
        self.assertEqual(self.rounds_read(out, A), list(range(1, cap + 1)))
        self.assertEqual(fake.writes[A], cap)

    def test_switch_off_single_round(self):
        """재위임을 끄면 부족 신고가 있어도 1바퀴로 끝난다(로그만이 아니라 실제 경로)."""
        short = {"원고": draft(1, SDH_KO), "충분": False, "부족": "사례가 부족하다"}
        out, fake = self.run_graph({A: [short], B: [{"원고": draft(1, SDH_EN), "충분": True, "부족": ""}]}, 재위임=False)
        self.assertEqual(out["plan"]["종료"], "재위임 꺼짐")
        self.assertEqual(out["plan"]["재위임기록"], [])
        self.assertEqual({r for *_, r in out["visited"]}, {1})
        self.assertEqual(fake.writes, {A: 1, B: 1})

    def test_metrics_from_fake_run(self):
        """가짜 실행도 ⑥ 평가까지 가고, 호출 수는 가짜가 받은 수와 같다(진짜 API로 샌 호출 없음)."""
        out, fake = self.run_graph({A: [{"원고": draft(2, SDH_KO), "충분": True, "부족": ""}],
                                    B: [{"원고": draft(2, SDH_EN), "충분": True, "부족": ""}]})
        m = out["metrics"]
        self.assertEqual(m["호출"], fake.calls)
        self.assertEqual(m["허위인용"], 0)
        self.assertEqual(m["무근거절"], 0)
        self.assertEqual(m["재위임절"], 0)
        self.assertTrue(re.search(r"^# 시험 보고서", out["report"], re.M))


if __name__ == "__main__":
    unittest.main(verbosity=2)
