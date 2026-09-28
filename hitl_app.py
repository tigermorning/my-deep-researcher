# -*- coding: utf-8 -*-
"""HITL(사람이 승인하는) 딥리서처 데모 — 조사를 새로 시작하고, 멈춘 건을 승인 화면에서 처리한다.

    streamlit run hitl_app.py
    DR_SAMPLE=1 streamlit run hitl_app.py   # 예시 코퍼스(지어낸 자료)로

graph.py의 노드를 그대로 쓰되(hitl.build), ⑥평가 뒤에 사람 승인 게이트(hitl.gate)를 하나 더
통과한다. 저장 위치도 output/reports/·runs.jsonl(제출 실험 집계)과 분리된
output/hitl(_sample)/에 둔다 — 이 데모의 실행은 기존 118+29실행 집계에 안 섞인다.

승인 기준(두 가지, 계산 가능 — hitl.py 상단 docstring·REPORT.md 참고):
- 인용 위험: metrics['허위인용'] 또는 metrics['범위밖큐'] > 0
- 미흡 위험: 바퀴 상한에 걸려 '충분: False'인 절이 그대로 종합됨(plan['종료'] == '바퀴 소진')
"""
import datetime
import json
import os
import sys
import threading
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SAMPLE = os.environ.get("DR_SAMPLE") == "1" or "--sample" in sys.argv
if SAMPLE:
    os.environ["DR_SAMPLE"] = "1"
QUESTIONS_FILE = ROOT / "data" / ("sample_questions.json" if SAMPLE else "questions.json")

st.set_page_config(page_title="HITL 딥리서처 승인 데모", layout="wide")


@st.cache_resource
def run_lock():
    """graph.py의 설정(스위치)·COST는 모듈 전역 — 세션 둘이 동시에 돌면 서로 덮는다(app.py와 같은 이유)."""
    return threading.Lock()


def questions():
    if not QUESTIONS_FILE.exists():
        return []
    return json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]


STAGE = {"plan": "① 기획", "plan_gate": "◐ 기획 승인", "dispatch": "② 배치", "researcher": "③ 조사관",
         "review": "④ 점검", "synthesize": "⑤ 종합", "evaluate": "⑥ 평가", "gate": "⑦ 발행 승인"}


def live_progress(box):
    box.caption("조사관 진행(청크 하나 읽을 때마다 갱신) · 아래는 노드가 끝날 때마다의 로그")
    table = box.empty()
    rows = {}

    def on_step(node, lines):
        if node == "읽기":
            e = lines[0]
            rows[(e["절"], e["바퀴"])] = e
            md = ["| 절 | 바퀴 | 읽음 | 방금 읽은 청크 |", "|---|---|---|---|"]
            for (sec, rnd), x in rows.items():
                flag = (" · 관련 없음" if x["관련없음"] else "") + (" · 메모 되물음" if x["되물음"] else "")
                md.append(f"| {sec} | {rnd} | {x['읽음']}/{x['예산']} | `{x['청크']}`{flag} |")
            table.markdown("\n".join(md))
            box.update(label=f"③ 조사관 읽는 중 — {sum(x['읽음'] for x in rows.values())}청크", expanded=True)
            return
        for ln in lines:
            box.code(ln, language=None)
        box.update(label=f"{STAGE.get(node, node)} 끝", expanded=True)

    return on_step


# ---------------------------------------------------------------- 사이드바: 새 조사 시작
st.sidebar.header("새 조사 시작")
if SAMPLE:
    st.sidebar.info("예시 코퍼스 모드 — 플랫폼·작품·규정·대사 전부 지어낸 자료")
qs = questions()
pick = st.sidebar.selectbox("질문", [f"{q['id']} [{q['type']}] {q['question'][:40]}…" for q in qs] + ["직접 입력"])
custom = st.sidebar.text_area("질문 직접 입력", disabled=pick != "직접 입력")
key = st.sidebar.text_input("OpenAI 키(비우면 환경변수·.env 사용)", type="password")
go = st.sidebar.button("실행", type="primary")

if go:
    if key:
        os.environ["OPENAI_API_KEY"] = key
    import hitl                      # 키를 넣은 뒤 불러온다(graph import가 키를 확인함)
    if pick == "직접 입력":
        qid, question = "custom", custom.strip()
    else:
        q = qs[[f"{q['id']} [{q['type']}] {q['question'][:40]}…" for q in qs].index(pick)]
        qid, question = q["id"], q["question"]
    if not question:
        st.sidebar.error("질문이 비어 있다.")
        st.stop()
    lock = run_lock()
    if not lock.acquire(blocking=False):
        st.sidebar.warning("다른 세션이 실행 중이다 — 끝난 뒤 다시 누른다.")
        st.stop()
    try:
        with st.status("조사 시작 — 보통 1~3분", expanded=True) as box:
            r = hitl.start(question, qid, on_step=live_progress(box))
            if r["pending"]:
                box.update(label="끝 — 승인 대기로 넘어감(아래 '승인 대기' 탭)", state="complete", expanded=False)
            else:
                box.update(label="끝 — 기준에 안 걸려 자동 저장됨", state="complete", expanded=False)
    finally:
        lock.release()
    st.session_state["last_thread"] = r["thread_id"]
    st.session_state["last_qid"] = qid

# ---------------------------------------------------------------- 본문
import hitl  # noqa: E402  (사이드바에서 이미 불러왔을 수도 있지만, 실행 없이 페이지만 열 때 대비)

tab_pending, tab_done = st.tabs(["승인 대기", "완료된 실행"])

with tab_pending:
    pend = hitl.pending_threads()
    if not pend:
        st.info("대기 중인 건이 없다. 왼쪽에서 새로 실행하거나, 기준에 걸리는 질문을 골라 본다.")
    for e in pend:
        payload = e["payload"] or {}
        kind = payload.get("종류", "발행")   # "기획"(◐, 조사 시작 전) 또는 "발행"(⑦, 저장 전)
        started = e.get("started_at", "")
        icon = "◐" if kind == "기획" else "🕘"
        with st.expander(f"{icon} [{kind} 게이트] {e['qid']} — {e['question'][:60]} (제출 {started})",
                          expanded=len(pend) == 1):
            st.markdown("**질문**")
            st.markdown(f"> {payload.get('질문', e['question'])}")
            st.markdown("**멈춘 이유**")
            for r in payload.get("멈춘 이유", []):
                st.warning(r)
            st.markdown("**근거**")
            ev = payload.get("근거", [])
            if ev:
                for x in ev:
                    st.markdown(f"- {x}")
            else:
                st.caption("(근거 사례 없음)")

            key_ns = e["thread_id"]
            draft_text = payload.get("AI 판정(보고서 초안)", "")
            toc = payload.get("목차", [])
            section_overrides = {}
            if kind == "기획":
                st.markdown("**AI 판정(목차 초안 — 배정검사가 이미 고친 뒤)**")
                st.table([{"절": t["절"], "역할": t.get("역할"), "시작문서": ", ".join(t.get("시작문서", [])),
                           "기준자료": ", ".join(t.get("기준자료", [])), "지시": t.get("지시", "")} for t in toc])
            else:
                st.markdown("**AI 판정(보고서 초안)**")
                st.markdown(draft_text if draft_text else "(초안 없음)")
            st.caption("통과시키면: " + payload.get("통과시키면", ""))

            action = st.radio("결정", ["승인", "수정 후 승인", "반려", "다시 판정"],
                               horizontal=True, key=f"action-{key_ns}")
            edited = None
            reason = ""
            directive = ""
            if action == "수정 후 승인" and kind == "기획":
                st.caption("절마다 지시문만 고쳐서 승인한다(자료 배정 자체를 바꾸려면 반려 후 다시 판정을 쓴다).")
                for t in toc:
                    new_instr = st.text_input(f"「{t['절']}」 지시", value=t.get("지시", ""),
                                               key=f"instr-{key_ns}-{t['절']}")
                    if new_instr != t.get("지시", ""):
                        section_overrides[t["절"]] = new_instr
            elif action == "수정 후 승인":
                edited = st.text_area("수정본(이 내용으로 저장된다)", value=draft_text, height=300, key=f"edit-{key_ns}")
            elif action == "반려":
                reason = st.text_input("반려 사유", key=f"reason-{key_ns}")
            elif action == "다시 판정":
                directive = st.text_input("AI에게 줄 재작성 지시", key=f"dir-{key_ns}")

            if st.button("제출", key=f"submit-{key_ns}"):
                decision_map = {"승인": "승인", "수정 후 승인": "수정후승인", "반려": "반려", "다시 판정": "다시판정"}
                answer = {"결정": decision_map[action], "사유": reason, "지시": directive}
                if edited is not None:
                    answer["수정본"] = edited
                elif section_overrides:
                    answer["수정본"] = section_overrides
                out = hitl.resume(key_ns, e["qid"], answer)
                st.session_state[f"resumed-{key_ns}"] = out
                st.rerun()

            resumed = st.session_state.get(f"resumed-{key_ns}")
            if resumed and resumed.get("run"):
                rec = resumed["out"]["plan"].get("승인기록") or resumed["out"]["plan"].get("기획승인기록", {})
                st.success(f"처리됨 — {rec.get('결정')} (저장: {resumed['run']})")
            elif resumed and resumed.get("pending"):
                st.info("처리됐지만 다음 게이트(또는 재기획)에서 또 멈췄다 — 목록을 새로고침해 이어서 처리한다.")
            if action == "다시 판정" and directive and kind == "발행" and st.session_state.get(f"resumed-{key_ns}"):
                if st.button("이 지시로 새로 실행", key=f"retry-{key_ns}"):
                    new_q = e["question"] + f"\n\n[담당자 재작성 지시] {directive}"
                    lock = run_lock()
                    if lock.acquire(blocking=False):
                        try:
                            with st.status("재실행 중", expanded=True) as box2:
                                hitl.start(new_q, e["qid"], on_step=live_progress(box2))
                        finally:
                            lock.release()
                        st.rerun()

with tab_done:
    rows = hitl.saved_runs()
    if not rows:
        st.info("완료된 실행이 아직 없다.")
    names = list(rows)
    if names:
        name = st.selectbox("실행 기록", names)
        r = rows[name]
        st.markdown(f"**질문** {r['question']}  ·  **결정** {r['decision']}")
        m = r.get("metrics", {})
        if m:
            c = st.columns(4)
            c[0].metric("절수", m.get("절수", "-"))
            c[1].metric("허위인용", m.get("허위인용", "-"))
            c[2].metric("범위밖큐", m.get("범위밖큐", "-"))
            c[3].metric("호출", m.get("호출", "-"))
        if r.get("report_file"):
            rf = hitl.OUT / r["report_file"]
            st.markdown(rf.read_text(encoding="utf-8") if rf.exists() else "(보고서 파일 없음)")
        else:
            st.caption("이 실행은 저장된 보고서가 없다(반려 또는 다시 판정 요청).")
        with st.expander("승인 기록"):
            st.markdown("**◐ 기획 게이트**")
            st.json(r.get("기획승인기록", {}))
            st.markdown("**⑦ 발행 게이트**")
            st.json(r.get("승인기록", {}) or "(기획 단계에서 끝나 여기까지 안 옴)")
        with st.expander("로그"):
            st.code("\n".join(r.get("log", [])) or "(로그 없음)")
