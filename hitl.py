# -*- coding: utf-8 -*-
"""HITL(사람이 승인하는) 게이트 — graph.py의 노드를 그대로 재사용하되, 승인 게이트 둘을 더 붙인
별도 그래프. graph.py 자체는 건드리지 않는다(제출 실험 118+29실행·ablation 집계 재현성 보존 —
HANDOFF.md 9절 "새 기능은 새 절을 더하거나 별도 문서로").

    streamlit run hitl_app.py

## 게이트 두 개 — 서로 다른 위험을 막는다
"사람이 맨 끝에만 있으면 왜곡이 이미 다 일어난 뒤에야 보게 되는 것 아닌가"라는 질문에서 하나를
더 붙였다. 그래서 이 그래프는 게이트가 둘이다.

- **◐ 기획 게이트** (①기획 뒤, ②배치 전): "이 조사를 이 목차로 시작해도 되는가" — 조사에
  청크 예산을 쓰기 **전에** 막는다. 막는 위험: 모델이 목차를 짤 때 코퍼스를 헷갈린 것
  (존재하지 않는 자료를 배정 · 질문이 안 부른 트랙을 넣음 · 트랙과 안 맞는 규정을 기준자료로 씀).
- **⑦ 발행 게이트** (⑥평가 뒤, 저장 전): "이 결과를 내보내도 되는가" — 이 프로젝트에서
  "결과가 바깥으로 나간다"는 것은 조사 보고서가 output/hitl/reports/에 완결된 실행으로 저장되어
  데모 화면에 공식 결과로 노출되는 순간이다.

둘은 서로 다른 위험을 막는다 — 기획 게이트가 통과해도(목차가 멀쩡해도) 조사 중에 원문을 잘못
읽거나 종합이 뜻을 비틀 수 있어 발행 게이트가 따로 필요하고, 반대로 발행 게이트만 있으면 이미
잘못 배정된 목차로 청크 예산을 다 쓴 뒤에야 사람이 그 사실을 안다(비용 낭비 + 결국 사람이
완성된 긴 보고서를 처음부터 다시 읽어야 왜곡을 찾음 — 헛읽기).

## 기획 게이트 기준 (①기획의 배정검사 check_plan이 이미 잡아낸 신호만 읽는다)
- 무효배정(목록에 없는 제목을 배정) · 질문밖트랙(질문이 안 부른 트랙을 넣음) · 규정불일치
  (트랙과 안 맞는 규정을 기준자료로 씀) 중 하나라도 있으면 멈춘다.
- **일부러 위험 신호로 안 쓰는 것**: 필수채움·절로승격·합친절. 이 셋은 배정검사가 거의 매번
  하는 정상적인 보정이라(예: 트랙 종류별 필수 규정을 자동으로 채워 넣는 것) 위험 신호로 쓰면
  거의 모든 실행에서 멈춰 헛멈춤만 늘어난다 — 강의 3강이 경고한 "헛멈춤 많으면 담당자가 내용을
  안 보고 도장만 찍는다"를 피하려고 골라냈다.

## 발행 게이트 기준 (⑥평가·④점검이 이미 만든 신호를 그대로 읽는다)
- **인용 위험**: metrics['허위인용'] 또는 metrics['범위밖큐']가 0보다 크다
  — 막는 위험: 인용(«»·큐 번호)이 원문과 안 맞는 채로 보고서가 나가는 것. 인용대조(check_quotes)가
  이미 자동으로 고치거나 지웠지만, 그래도 남은 경보는 사람이 원문과 대조해야 한다.
- **미흡 위험**: plan['종료'] == '바퀴 소진'이면서 아직 '충분': False인 절이 남아 있다
  — 막는 위험: 조사관 스스로 "아직 부족하다"고 신고했는데 재위임 바퀴 상한에 걸려 그대로
  종합되는 것. 이 신호가 없는 절(충분: True로 끝났거나, 애초에 재위임이 필요 없었던 절)은 AI가
  스스로 충분하다고 확인했으므로 사람이 안 봐도 된다.

두 게이트 다 새 휴리스틱을 안 만든다 — 이미 graph.py가 계산해 두던 신호만 읽는다.
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


# ---------------------------------------------------------------- ◐ 기획 게이트
REPLAN_MARK = "[담당자 재기획 지시]"
REPLAN_CAP = 1   # "다시 판정"을 실제로 되돌리는 최대 횟수 — 넘으면 그대로 진행(무한 루프 방지)


def _plan_reasons(s):
    """기획 위험 판정 — LLM 호출 없음, ①기획의 배정검사(check_plan)가 이미 잡아 둔 것만 본다."""
    p = s.get("plan") or {}
    fixes = {k: p.get(k, []) for k in ("무효배정", "질문밖트랙", "규정불일치")}
    names = {"무효배정": "목록에 없는 제목을 배정함", "질문밖트랙": "질문이 안 부른 트랙을 넣음",
             "규정불일치": "트랙과 안 맞는 규정을 기준자료로 넣음"}
    reasons = [("기획 위험", f"{names[k]}: {', '.join(map(str, v))}") for k, v in fixes.items() if v]
    return reasons, fixes


def plan_gate(s):
    """①기획 뒤, ②배치(조사 시작) 전에 멈춘다. interrupt() 앞은 순수 계산(_plan_reasons)만
    — 재개 시 이 노드도 처음부터 다시 실행되므로 부작용을 앞에 두지 않는다(⑦ gate와 같은 원칙)."""
    reasons, fixes = _plan_reasons(s)
    p = s["plan"]
    if not reasons:
        return {"plan": {**p, "기획승인기록": {"결정": "자동통과", "사유": "", "지시": "", "멈춘이유": []}},
                "log": ["◐ 기획승인   배정검사가 고칠 게 없음 — 자동 통과"]}
    toc_view = [{"절": t["절"], "역할": t.get("역할"), "시작문서": t.get("시작문서", []),
                 "기준자료": t.get("기준자료", []), "지시": t.get("지시", "")} for t in p["목차"]]
    payload = {
        "종류": "기획",
        "질문": s["question"],
        "멈춘 이유": [f"{label} — {desc}" for label, desc in reasons],
        "근거": [f"{k}: {v}" for k, v in fixes.items() if v],
        "목차": toc_view,
        "통과시키면": "이 목차 그대로 ② 배치부터 조사가 시작된다(청크 예산이 실제로 소비된다)",
    }
    answer = interrupt(payload)
    decision = (answer or {}).get("결정") or "반려"
    replans_so_far = s["question"].count(REPLAN_MARK)
    if decision == "다시판정" and replans_so_far >= REPLAN_CAP:
        directive = (answer or {}).get("지시", "")
        record = {"결정": "승인", "사유": f"재기획 상한 도달 — 지시 '{directive}'는 반영 못 하고 그대로 진행",
                   "지시": "", "멈춘이유": [f"{label} — {desc}" for label, desc in reasons]}
        return {"plan": {**p, "기획승인기록": record},
                "log": [f"◐ 기획승인   승인 ({record['사유']})"]}
    if decision == "다시판정":
        directive = (answer or {}).get("지시", "")
        record = {"결정": decision, "사유": "", "지시": directive,
                  "멈춘이유": [f"{label} — {desc}" for label, desc in reasons]}
        return {"question": f"{s['question']}\n\n{REPLAN_MARK} {directive}",
                "plan": {**p, "기획승인기록": record},
                "log": [f"◐ 기획승인   다시판정 — {directive}"]}
    if decision == "수정후승인" and (answer or {}).get("수정본"):
        overrides = answer["수정본"]
        toc = [dict(t) for t in p["목차"]]
        for t in toc:
            if t["절"] in overrides:
                t["지시"] = overrides[t["절"]]
        p = {**p, "목차": toc}
    record = {"결정": decision, "사유": (answer or {}).get("사유", ""), "지시": "",
              "멈춘이유": [f"{label} — {desc}" for label, desc in reasons]}
    line = f"◐ 기획승인   {decision}" + (f" ({record['사유']})" if record["사유"] else "")
    return {"plan": {**p, "기획승인기록": record}, "log": [line]}


def route_plan_gate(s):
    rec = s["plan"].get("기획승인기록", {})
    if rec.get("결정") == "다시판정":
        return "plan"
    if rec.get("결정") == "반려":
        return END
    return "dispatch"


# ---------------------------------------------------------------- ⑦ 발행 게이트
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
        "종류": "발행",
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
    graph_.add_node("plan_gate", plan_gate)
    graph_.add_node("gate", gate)
    graph_.add_edge(START, "plan")
    graph_.add_edge("plan", "plan_gate")
    graph_.add_conditional_edges("plan_gate", route_plan_gate, ["plan", "dispatch", END])
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
    남기고 output/hitl/reports/에는 안 올린다 — 그 실행은 '공식 결과'가 아니다.
    기획 게이트에서 반려되면 조사 자체가 시작 안 돼 '승인기록'(발행 게이트 몫)이 아예 없다 —
    이 경우는 metrics·report 없이 기획 단계 감사 기록만 남긴다."""
    plan_rec = out["plan"].get("기획승인기록", {})
    gate_rec = out["plan"].get("승인기록")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{qid}_{thread_id.split('-')[-1]}_{stamp}"
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    if gate_rec is None:
        decision = f"기획{plan_rec.get('결정', '반려')}"
        row = {"run": name, "thread_id": thread_id, "qid": qid, "question": out["question"], "decision": decision,
               "기획승인기록": plan_rec, "metrics": {}, "log": out.get("log", []),
               "plan": {k: v for k, v in out["plan"].items() if not k.startswith("_") and k != "채택"}}
        (OUT / "runs" / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        return name
    decision = gate_rec.get("결정", "자동통과")
    row = {"run": name, "thread_id": thread_id, "qid": qid, "question": out["question"], "decision": decision,
           "기획승인기록": plan_rec, "승인기록": gate_rec, "metrics": out.get("metrics", {}), "log": out.get("log", []),
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
