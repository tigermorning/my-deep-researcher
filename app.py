# -*- coding: utf-8 -*-
"""딥리서처 데모 — 보고서와 함께 절마다 누가 무엇을 읽고 무엇을 썼는지 보여 준다.

    streamlit run app.py

- 지난 실행 보기: output/runs/*.json(로컬 전용, 메모 포함)이 있으면 그것을, 없으면 output/runs.jsonl(메모 길이만)을 읽는다
  (예시 모드는 output/sample/ 아래 같은 파일)
- 새로 실행: data/corpus.json(로컬에서 scripts/build_corpus.py로 만듦, 예시 모드는 data/sample_corpus.json)과 OpenAI 키가 있어야 한다
  키는 환경변수 → .env → ~/Documents/openai_key.env 순, 또는 옆 칸에 붙여 넣는다(이 세션 안에서만 쓰고 저장하지 않음)
- 예시 코퍼스(지어낸 자료)로: DR_SAMPLE=1 streamlit run app.py (또는 streamlit run app.py -- --sample)
  → data/sample_*.json을 읽고 output/sample/을 보여 준다
"""
import json
import os
import re
import sys
import threading
from pathlib import Path

import streamlit as st

import metrics

ROOT = Path(__file__).resolve().parent
SAMPLE = os.environ.get("DR_SAMPLE") == "1" or "--sample" in sys.argv   # graph.py와 같은 조건 — 어긋나면 질문·저장 폴더가 갈린다
if SAMPLE:
    os.environ["DR_SAMPLE"] = "1"
OUT = ROOT / "output" / "sample" if SAMPLE else ROOT / "output"
CORPUS_FILE = ROOT / "data" / ("sample_corpus.json" if SAMPLE else "corpus.json")
QUESTIONS_FILE = ROOT / "data" / ("sample_questions.json" if SAMPLE else "questions.json")
st.set_page_config(page_title="자막 규정 딥리서처", layout="wide")


@st.cache_data(ttl=5)
def list_runs():
    rows = {}
    if (OUT / "runs.jsonl").exists():
        for line in (OUT / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rows[r["run"]] = r
    for f in (OUT / "runs").glob("*.json") if (OUT / "runs").exists() else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        rows[r["run"]] = r                  # 메모까지 있는 쪽이 이긴다
    return dict(sorted(rows.items(), reverse=True))


@st.cache_resource
def run_lock():
    """graph.py의 설정(스위치)·COST는 모듈 전역이다 — 세션 둘이 동시에 돌면 서로의 스위치·비용을 덮는다.
    streamlit 프로세스 하나에 잠금 하나를 두고 실행을 한 번에 하나만 받는다."""
    return threading.Lock()


def baseline_budget(qid):
    """대조군 예산 = 같은 문항 '기본' 실행들이 실제로 읽은 청크 수의 평균(ablation.py와 같은 규칙). 기록이 없으면 None(기본 24)."""
    if qid == "custom":                 # 직접 입력한 질문끼리는 같은 문항이 아니다
        return None
    got = [len(r["visited"]) for r in list_runs().values()
           if r["qid"] == qid and r["tag"] == "기본" and r["metrics"].get("절수")
           and r["metrics"].get("읽은청크") and not r["metrics"].get("JSON실패")]   # 집계에서 빼는 빈 실행은 평균에도 안 넣는다
    return round(sum(got) / len(got)) if got else None


STAGE = {"plan": "① 기획", "dispatch": "② 배치", "researcher": "③ 조사관", "review": "④ 점검",
         "synthesize": "⑤ 종합", "evaluate": "⑥ 평가"}


def live_progress(box):
    """graph.run / baseline.run의 on_step — LangGraph 스트리밍으로 받은 진행을 화면에 바로 그린다.
    - 노드가 끝나면 그 노드의 로그 줄(무엇을 배정했고 몇 청크 읽고 몇 자 썼나)
    - 조사관이 청크를 하나 읽을 때마다 절별 진행표(읽은 수/예산 · 방금 읽은 청크 · 관련 없음·되물음 표시)
    원문은 오지 않는다(청크 id와 개수만)."""
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
            # expanded를 매번 넘긴다 — 라벨만 바꾸면 streamlit이 상태 창을 접었다
            box.update(label=f"③ 조사관 읽는 중 — {sum(x['읽음'] for x in rows.values())}청크", expanded=True)
            return
        for ln in lines:
            box.code(ln, language=None)
        box.update(label=f"{STAGE.get(node, node)} 끝", expanded=True)

    return on_step


def questions():
    return json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]


# ---------------------------------------------------------------- 사이드바: 실행
st.sidebar.header("새로 실행")
if SAMPLE:
    st.sidebar.info("예시 코퍼스 모드 — 플랫폼·작품·규정·대사 전부 지어낸 자료(data/sample_corpus.json)")
qs = questions()
pick = st.sidebar.selectbox("질문", [f"{q['id']} [{q['type']}] {q['question'][:40]}…" for q in qs] + ["직접 입력"])
custom = st.sidebar.text_area("질문 직접 입력", disabled=pick != "직접 입력")
mode = st.sidebar.radio("구성", ["팀(기획→조사관→점검→종합)", "혼자 하는 대조군"])
sw = {}
if mode.startswith("팀"):
    st.sidebar.caption("스위치 — 끄면 그 장치의 코드 경로를 실제로 건너뛴다")
    for k, desc in [("배정검사", "① 목차 배정을 코드로 검사"), ("남의구역", "② 다른 절 구역 피하기"), ("재위임", "④ 부족 신고한 절 다시 보내기"),
                    ("인용대조", "③ 메모·원고의 큐 번호와 인용문을 원문과 대조")]:
        sw[k] = st.sidebar.checkbox(f"{k} — {desc}", value=True)
key = st.sidebar.text_input("OpenAI 키(비우면 환경변수·.env 사용)", type="password")
go = st.sidebar.button("실행", type="primary")

if go:
    if key:
        os.environ["OPENAI_API_KEY"] = key
    if not CORPUS_FILE.exists():
        st.sidebar.error(f"{CORPUS_FILE.relative_to(ROOT).as_posix()}이 없다 — "
                         + ("`python scripts/make_sample_corpus.py`로 다시 만든다" if SAMPLE else
                            "원본이 있으면 `python scripts/build_corpus.py`, 없으면 예시 코퍼스로: `DR_SAMPLE=1 streamlit run app.py`"))
        st.stop()
    import graph as g                     # 키를 넣은 뒤에 불러온다(불러올 때 키를 확인함)
    if pick == "직접 입력":
        qid, question = "custom", custom.strip()
    else:
        q = qs[[f"{q['id']} [{q['type']}] {q['question'][:40]}…" for q in qs].index(pick)]
        qid, question = q["id"], q["question"]
    lock = run_lock()
    if not lock.acquire(blocking=False):
        st.sidebar.warning("다른 세션이 실행 중이다 — 끝난 뒤 다시 누른다(스위치·비용 카운터가 전역이라 한 번에 하나만 돌린다)")
        st.stop()
    try:
        if mode.startswith("팀"):
            with st.status("조사 시작 — 팀은 보통 1~3분", expanded=True) as box:
                saved = dict(g.설정["스위치"])
                g.설정["스위치"].update(sw)
                try:
                    offs = [k for k, v in sw.items() if not v]
                    out = g.run(question, qid, "기본" if not offs else "off-" + "-".join(offs), quiet=True,
                                on_step=live_progress(box))
                finally:
                    g.설정["스위치"].update(saved)
                box.update(label="끝 — 아래에서 보고서를 본다", state="complete", expanded=False)
        else:
            import baseline
            budget = baseline_budget(qid)
            note = f"같은 문항 팀 실행의 평균 읽기량 {budget}청크" if budget else "팀 기록이 없어 기본 예산"
            with st.status(f"대조군 조사 시작 — {note}", expanded=True) as box:
                out = baseline.run(question, qid, budget, quiet=True, on_step=live_progress(box))
                box.update(label="끝 — 아래에서 보고서를 본다", state="complete", expanded=False)
    finally:
        lock.release()
    list_runs.clear()
    st.session_state["run"] = out["run"]

# ---------------------------------------------------------------- 본문: 실행 고르기
runs = list_runs()
if not runs:
    st.info("아직 실행 기록이 없다. 왼쪽에서 질문을 골라 실행한다.")
    st.stop()
names = list(runs)
want = st.session_state.get("run") or st.query_params.get("run")     # ?run=실행이름 으로 바로 열기(공유·캡처용)
default = names.index(want) if want in runs else 0
name = st.selectbox("실행 기록", names, index=default)
r = runs[name]
m = r["metrics"]

st.title("자막 규정 딥리서처")
st.markdown(f"**질문** {r['question']}")
alarms = {k: m.get(k) for k, (kind, _, _) in metrics.SPEC.items() if kind == "경보"}
bad = {k: v for k, v in alarms.items() if v}
c = st.columns(6)
c[0].metric("설정", r["tag"])
c[1].metric("절", m["절수"])
c[2].metric("읽은 청크", m["읽은청크"])
c[3].metric("격리율", f"{m['격리율']}%")
c[4].metric("호출", m["호출"])
c[5].metric("경보", sum(bad.values()) if bad else 0)
if bad:
    st.error("경보: " + ", ".join(f"{k} {v}" for k, v in bad.items()) + " — 아래 '절마다' 탭에서 어느 절인지 확인")

tab_rep, tab_sec, tab_plan, tab_met, tab_log = st.tabs(["보고서", "절마다 누가 무엇을", "기획", "지표", "로그"])

with tab_rep:
    rf = OUT / r["report_file"]
    st.markdown(rf.read_text(encoding="utf-8") if rf.exists() else "(보고서 파일 없음)")

with tab_sec:
    toc = r["plan"]["목차"]
    for sec in r["sections"]:
        i = sec["번호"]
        t = toc[i] if i < len(toc) else {}
        read_docs = {re.sub(r"\s*#\d+/\d+$", "", c) for c in sec["읽은청크"]}
        cites = [tuple(x) for x in sec["인용"]]
        false = [c for c, _ in cites if c not in read_docs]
        head = f"{sec['절']} — {t.get('역할', '')} · {sec['바퀴']}바퀴 · {len(sec['읽은청크'])}청크 · 인용 {len(cites)}"
        with st.expander(head + (" ⚠ 허위인용" if false else "") + ("" if sec["충분"] else " · 부족 신고"), expanded=False):
            a, b = st.columns(2)
            a.markdown("**배정(기획)**")
            a.markdown("시작문서: " + ", ".join(f"`{d}`" for d in t.get("시작문서", [])))
            a.markdown("기준자료: " + (", ".join(f"`{d}`" for d in t.get("기준자료", [])) or "-"))
            a.markdown(f"지시: {t.get('지시', '')}")
            b.markdown("**읽은 순서**")
            visited = {(v[1]): v[2] for v in r.get("visited", []) if v[0] == i}
            for n, note in enumerate(sec["메모"], 1):
                cid = note["청크"]
                text = note.get("메모")
                irrelevant = note.get("관련없음", text is not None and re.sub(r"[\s.。!]", "", text) == "관련없음")
                b.markdown(f"{n}. `{cid}` ({visited.get(cid, '이전')}바퀴)" + (" — _관련 없음_" if irrelevant else ""))
            st.markdown("**쓴 것(원고)**")
            st.markdown(sec["원고"] or "_(재료를 찾지 못해 원고 없음)_")
            if false:
                st.warning("읽지 않은 자료를 인용: " + ", ".join(dict.fromkeys(false)))
            if not sec["충분"]:
                st.info(f"부족 신고: {sec['부족']}")
            if any("메모" in n for n in sec["메모"]):
                with st.popover("메모 보기(원문 발췌 포함 — 로컬 전용)"):
                    for note in sec["메모"]:
                        st.markdown(f"**{note['청크']}**\n\n{note['메모']}")

with tab_plan:
    p = r["plan"]
    fixes = {k: p.get(k, []) for k in ["무효배정", "질문밖트랙", "규정불일치", "합친절", "필수채움", "절로승격"]}
    st.markdown("**코드가 고친 것**: " + (", ".join(f"{k} {len(v)}" for k, v in fixes.items() if v) or "없음"))
    for k, v in fixes.items():
        if v:
            st.caption(f"{k}: " + ", ".join(map(str, v)))
    st.table([{"절": t["절"], "역할": t.get("역할"), "시작문서": ", ".join(t["시작문서"]),
               "기준자료": ", ".join(t.get("기준자료", [])), "예산": t.get("예산"), "기준예산": t.get("기준예산", "-")}
              for t in p["목차"]])
    st.caption(f"종료 사유: {p.get('종료', '')} · 재위임: {', '.join(p.get('재위임기록', [])) or '없음'}"
               f" · 지난 원고 지킴: {', '.join(p.get('되돌림', [])) or '없음'}")

with tab_met:
    st.table([{"지표": k, "값": m.get(k), "종류": kind, "보는 장치": dev, "뜻": desc}
              for k, (kind, dev, desc) in metrics.SPEC.items()])
    st.caption("경보는 0이어야 정상. 견줌 지표는 설정끼리 비교할 때만 뜻이 있고, 한 번 돌린 값으로 단정하지 않는다.")

with tab_log:
    st.code("\n".join(r.get("log", [])) or "(로그 없음 — 대조군이거나 예전 실행)")
