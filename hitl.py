# -*- coding: utf-8 -*-
"""HITL(사람이 승인하는) 게이트 — graph.py의 노드를 그대로 재사용하되, ⑥평가 뒤에 승인 게이트를
하나 더 붙인 별도 그래프. graph.py 자체는 건드리지 않는다(제출 실험 118+29실행·ablation 집계
재현성 보존 — HANDOFF.md 9절 "새 기능은 새 절을 더하거나 별도 문서로").

    streamlit run hitl_app.py

## 결과가 바깥으로 나가는 자리
이 프로젝트에서 "결과가 바깥으로 나간다"는 것은 조사 보고서가 output/hitl/reports/에 완결된
실행으로 저장되어 데모 화면에 공식 결과로 노출되는 순간이다. 그 저장 직전(⑥평가 뒤)에 사람이
막을 자리를 둔다.

## 승인 기준 (계산 가능, 둘 다 ⑥평가·④점검이 이미 만든 신호를 그대로 읽는다 — 새 휴리스틱을 안 만든다)
- **인용 위험**: metrics['허위인용'] 또는 metrics['범위밖큐']가 0보다 크다
  — 막는 위험: 인용(«»·큐 번호)이 원문과 안 맞는 채로 보고서가 나가는 것. 인용대조(check_quotes)가
  이미 자동으로 고치거나 지웠지만, 그래도 남은 경보는 사람이 원문과 대조해야 한다.
- **미흡 위험**: plan['종료'] == '바퀴 소진'이면서 아직 '충분': False인 절이 남아 있다
  — 막는 위험: 조사관 스스로 "아직 부족하다"고 신고했는데 재위임 바퀴 상한에 걸려 그대로
  종합되는 것. 이 신호가 없는 절(충분: True로 끝났거나, 애초에 재위임이 필요 없었던 절)은 AI가
  스스로 충분하다고 확인했으므로 사람이 안 봐도 된다.
"""
import contextlib
import datetime
import json
import uuid
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import graph as g

ROOT = g.ROOT
OUT = ROOT / "output" / ("hitl_sample" if g.SAMPLE else "hitl")


# ---------------------------------------------------------------- ⑦ 승인 게이트
def _reasons(s):
    """두 승인 기준을 판정한다. LLM 호출 없음 — ⑥평가·④점검이 이미 계산해 둔 신호만 읽는다."""
    m, p = s.get("metrics") or {}, s.get("plan") or {}
    out = []
    n = (m.get("허위인용", 0) or 0) + (m.get("범위밖큐", 0) or 0)
    if n:
        out.append(("인용 위험", f"허위인용 {m.get('허위인용', 0)}건 · 범위밖큐 {m.get('범위밖큐', 0)}건 "
                                "— 인용이 원문과 안 맞을 수 있다"))
    if p.get("종료") == "바퀴 소진":
        adopted = g._latest(p.get("채택", {}))
        short = [v["절"] for v in adopted.values() if not v.get("충분", True)]
        if short:
            out.append(("미흡 위험", "바퀴 상한에 걸려 부족 신고를 못 채운 절: " + ", ".join(short)))
    return out


def _evidence(s):
    """근거로 보여줄 구체적 사례 — 절마다 인용대조가 잡은 문장 · 부족 신고 사유 · 맺음말 허위인용."""
    p = s.get("plan") or {}
    adopted = g._latest(p.get("채택", {}))
    ev = []
    for v in adopted.values():
        qc = v.get("인용대조") or {}
        for sent, kind in qc.get("사례", []):
            ev.append(f"[{v['절']}] ({kind}) {sent}")
        if not v.get("충분", True):
            ev.append(f"[{v['절']}] 부족 신고: {v.get('부족', '')}")
    if p.get("맺음말허위인용"):
        ev.append("맺음말에서 목록 밖 인용: " + ", ".join(p["맺음말허위인용"]))
    return ev


def gate(s):
    """⑤종합 뒤 ⑥평가가 끝난 상태를 받아, 기준에 걸리면 interrupt로 멈추고 담당자 답을 기다린다.
    주의: interrupt() 앞에는 순수 계산(_reasons·_evidence)만 둔다 — 재개 시 이 노드는 처음부터
    다시 실행되므로(바깥으로 나가는 동작은 이 자리에 두지 말 것, 강의 2강 "멈춘 단계의 재실행" 원칙),
    실제 저장은 노드 바깥(hitl.save_result)에서 담당자의 답이 온 뒤에만 한다."""
    reasons = _reasons(s)
    if not reasons:
        return {"plan": {**s["plan"], "승인기록": {"결정": "자동통과", "사유": "", "지시": "", "멈춘이유": []}},
                "log": ["⑦ 승인   기준에 안 걸림 — 자동 통과"]}
    payload = {
        "질문": s["question"],
        "멈춘 이유": [f"{label} — {desc}" for label, desc in reasons],
        "근거": _evidence(s)[:20],
        "AI 판정(보고서 초안)": s["report"],
        "통과시키면": f"{(OUT / 'reports').as_posix()} 에 이 실행이 공식 결과로 저장된다",
    }
    answer = interrupt(payload)
    decision = (answer or {}).get("결정") or "반려"
    report = s["report"]
    if decision == "수정후승인" and (answer or {}).get("수정본"):
        report = answer["수정본"]
    record = {"결정": decision, "사유": (answer or {}).get("사유", ""), "지시": (answer or {}).get("지시", ""),
              "멈춘이유": [f"{label} — {desc}" for label, desc in reasons]}
    line = f"⑦ 승인   {decision}" + (f" ({record['사유']})" if record["사유"] else "")
    return {"report": report, "plan": {**s["plan"], "승인기록": record}, "log": [line]}


# ---------------------------------------------------------------- 그래프 (graph.py 노드 재사용)
_stack = contextlib.ExitStack()
_saver = None


def _shared_checkpointer():
    """SqliteSaver는 본디 with문 컨텍스트. Streamlit은 상호작용마다 스크립트를 처음부터 다시
    돌리므로, 프로세스가 사는 동안 한 번만 열어 ExitStack으로 붙잡아 둔다(대기 목록이 재실행마다
    사라지면 안 된다 — 강의 4강 "대기 건 보관하기")."""
    global _saver
    if _saver is None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        OUT.mkdir(parents=True, exist_ok=True)
        _saver = _stack.enter_context(SqliteSaver.from_conn_string(str(OUT / "checkpoints.sqlite")))
    return _saver


def build(checkpointer=None):
    graph_ = StateGraph(g.State)
    for name in ["plan", "dispatch", "researcher", "review", "synthesize", "evaluate"]:
        graph_.add_node(name, getattr(g, name))
    graph_.add_node("gate", gate)
    graph_.add_edge(START, "plan")
    graph_.add_edge("plan", "dispatch")
    graph_.add_conditional_edges("dispatch", g.fanout, ["researcher", "review"])
    graph_.add_edge("researcher", "review")
    graph_.add_conditional_edges("review", g.route, ["dispatch", "synthesize"])
    graph_.add_edge("synthesize", "evaluate")
    graph_.add_edge("evaluate", "gate")
    graph_.add_edge("gate", END)
    return graph_.compile(checkpointer=checkpointer or _shared_checkpointer())


# ---------------------------------------------------------------- 대기 목록 · 저장
def _registry_file():
    return OUT / "threads.json"


def _registry():
    f = _registry_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _registry_add(entry):
    reg = _registry()
    reg.append(entry)
    OUT.mkdir(parents=True, exist_ok=True)
    _registry_file().write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def save_result(out, thread_id, qid):
    """결정이 승인·수정후승인·자동통과면 보고서를 저장한다. 반려·다시판정은 감사 기록(runs/*.json)만
    남기고 output/hitl/reports/에는 안 올린다 — 그 실행은 '공식 결과'가 아니다."""
    decision = out["plan"].get("승인기록", {}).get("결정", "자동통과")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{qid}_{thread_id.split('-')[-1]}_{stamp}"
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    row = {"run": name, "thread_id": thread_id, "qid": qid, "question": out["question"], "decision": decision,
           "승인기록": out["plan"].get("승인기록", {}), "metrics": out.get("metrics", {}), "log": out.get("log", []),
           "plan": {k: v for k, v in out["plan"].items() if not k.startswith("_") and k != "채택"}}
    if decision in ("자동통과", "승인", "수정후승인"):
        import metrics   # 보고서 파일에는 작품 제목에서 트랙 종류를 뗀 표기로(graph.save와 같은 규칙)
        (OUT / "reports").mkdir(parents=True, exist_ok=True)
        (OUT / "reports" / f"{name}.md").write_text(metrics.display_titles(out["report"], metrics.track_labels(g.META)),
                                                    encoding="utf-8")
        row["report_file"] = f"reports/{name}.md"
    (OUT / "runs" / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return name


# ---------------------------------------------------------------- 실행 · 재개
def start(question, qid="custom", on_step=None):
    """새 thread_id로 처음부터 실행한다. 기준에 안 걸리면 그 자리에서 끝까지 가서 자동 저장,
    걸리면 interrupt에서 멈춘 채로 돌아온다(pending=True) — 담당자 답은 resume()으로 넣는다."""
    thread_id = f"{qid}-{uuid.uuid4().hex[:8]}"
    app = build()
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 80}
    for k in g.COST:
        g.COST[k] = 0
    if on_step is None:
        out = app.invoke({"question": question}, cfg)
    else:
        out = None
        for mode, chunk in app.stream({"question": question}, cfg, stream_mode=["updates", "values", "custom"]):
            if mode == "values":
                out = chunk
                continue
            if mode == "custom":
                on_step("읽기", [chunk])
                continue
            for node, upd in chunk.items():
                on_step(node, (upd or {}).get("log", []) if isinstance(upd, dict) else [])
    _registry_add({"thread_id": thread_id, "qid": qid, "question": question,
                   "started_at": datetime.datetime.now().isoformat(timespec="seconds")})
    pending = bool(out and "__interrupt__" in out)
    name = None if pending else save_result(out, thread_id, qid)
    return {"thread_id": thread_id, "pending": pending, "out": out, "run": name}


def peek(thread_id):
    """대기 중인 건의 현재 상태 — get_state로 승인 화면에 보여줄 payload를 그대로 꺼낸다."""
    app = build()
    st_ = app.get_state({"configurable": {"thread_id": thread_id}})
    pending = bool(st_.next)
    payload = None
    if pending:
        for t in st_.tasks:
            if t.interrupts:
                payload = t.interrupts[0].value
                break
    return {"pending": pending, "values": st_.values, "payload": payload}


def resume(thread_id, qid, answer):
    """담당자 답(결정·사유·지시·수정본)을 넣어 멈춘 자리부터 이어간다."""
    app = build()
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 80}
    out = app.invoke(Command(resume=answer), cfg)
    pending = bool(out and "__interrupt__" in out)
    name = None if pending else save_result(out, thread_id, qid)
    return {"pending": pending, "out": out, "run": name}


def pending_threads():
    """등록된 thread_id 중 아직 사람 답을 기다리는 것만 골라, 화면에 쓸 payload와 함께 돌려준다."""
    out = []
    for e in _registry():
        st_ = peek(e["thread_id"])
        if st_["pending"]:
            out.append({**e, **st_})
    return out


def history(thread_id):
    """REPORT.md·데모의 '실행 결과' 절용 — 체크포인트가 실제로 몇 개 쌓였는지 그대로 노출(강의 2강)."""
    app = build()
    return list(app.get_state_history({"configurable": {"thread_id": thread_id}}))


def saved_runs():
    """output/hitl/runs/*.json 전체 — 완료(자동통과·승인·수정후승인·반려·다시판정 기록 포함).
    최신 실행이 먼저 오도록 파일 수정 시각으로 정렬한다(run 이름은 qid_thread_시각 순이라
    qid로 시작해 문자열 정렬로는 최신순이 안 된다 — 예: 'q11_...'이 'q10_...'보다 항상 앞섬)."""
    d = OUT / "runs"
    if not d.exists():
        return {}
    files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    rows = {}
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        rows[r["run"]] = r
    return rows
