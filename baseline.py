# -*- coding: utf-8 -*-
"""혼자 하는 대조군 — 코디네이터도 분업도 없이 조사관 한 명이 같은 자료·모델·도구·읽기 예산으로 보고서를 쓴다.

    python baseline.py q03                 # 예산 = 절수 × (절예산 + 기준예산) = 기본 24청크
    python baseline.py q03 --budget 16     # 팀 실행이 실제로 받은 예산에 맞출 때(ablation.py가 씀)
    python baseline.py s02 --sample        # 공개용 예시 코퍼스로(graph.py와 같다)

공정성
- 같은 자료: 코디네이터가 보는 카드 목록을 그대로 보고 출발 자료를 고른다
- 같은 도구: graph.py의 frontier(후보) · pick_next(고르기) · read_one(맞대기 보기 포함) · 인용 추출을 그대로 쓴다
- 같은 예산: 읽은 청크 수로 맞춘다. 끝나면 예산소진율을 찍어 다 썼는지 확인한다
- 다른 것: 절 분할 · 남의 구역 · 재위임 · 종합이 없다. 메모가 한 사람에게 다 쌓이고, 그 사람이 한 번에 보고서를 쓴다
- 위아래가 없으니 격리율은 100%로 둔다(본 글자 전부를 보고서 쓰는 사람이 봤다)
"""
import sys

import graph as g


def with_asked(question, seeds):
    """대조군 공정성(F): 질문이 부른 트랙이 시작문서에 하나도 없으면 코드가 맨 앞에 넣는다(최대 셋, 전체 6건 이하).
    팀은 기획 검사가 질문이 부른 트랙을 빠짐없이 배정하는데, 대조군은 모델이 규정만 골라
    q06·q08·q09에서 트랙을 0청크 읽었다 — 비교가 '분업'이 아니라 '트랙을 읽었나'를 재게 된다."""
    named = {m["work"] for m in g.META.values() if m["type"] == "track" and m["work"] in question}
    pool = g.asked_tracks(question, named)
    # 질문이 트랙 이름 낱말(예: '일본어')까지 짚은 트랙을 원문 쪽 트랙보다 앞에 — asked_tracks는 원문 쪽을 늘 포함한다
    # 회차도 본다 — q08(E06)에 같은 작품 E01 SDH가 먼저 들어왔다
    hit = lambda d: all(tok in question for tok in g.META[d]["track"].split())
    ep = lambda d: not g.META[d]["ep"] or g.META[d]["ep"] in question
    asked = sorted((d for d in g.DOCS if d in pool), key=lambda d: (not ep(d), not hit(d)))
    if not asked or any(g._is_track(s) and g._doc_of(s) in asked for s in seeds):
        return seeds
    add = asked[:3]
    rest = [s for s in seeds if s not in add]
    return add + rest[: max(6 - len(add), 1)]      # 모델이 고른 것도 최소 하나는 남긴다


def pick_start(question):
    cards = "\n".join(g.card(t) for t in g.DOCS)
    prompt = f"""너는 자막 규정 조사관이다. 혼자서 아래 질문에 답할 보고서를 쓴다. 먼저 읽기 시작할 자료를 고른다.

질문: {question}

- 시작문서: 먼저 읽을 트랙이나 규정 1~6건
- 기준자료: 대조할 규정 0~4건
- 제목은 아래 자료 목록의 «» 안 글자 그대로 옮겨라.

자료 목록
{cards}

JSON으로만 답하라: {{"시작문서": ["..."], "기준자료": ["..."]}}"""
    for attempt in range(2):
        out = g.ask(prompt, "coord", as_json=True)
        raw = list(map(g._clean, out.get("시작문서", []) or []))
        seeds = [d for d in raw if d in g.DOCS or d in g.CHUNKS]
        refs = [d for d in map(g._clean, out.get("기준자료", []) or []) if d in g.DOCS and d not in seeds]
        if seeds:
            return with_asked(question, seeds[:6]), refs[:4]
        # 맞는 제목이 하나도 없으면 읽을 것 없이 빈 보고서로 끝난다(q05에서 1호출·0청크 실행이 나옴) — 한 번 되묻는다
        prompt += f"\n\n방금 고른 시작문서 {raw}는 목록에 없는 제목이다. 목록의 «» 안 글자를 그대로 옮겨 다시 골라라."
    raise SystemExit(f"대조군 시작 자료를 고르지 못함: {raw}")   # 빈 실행을 저장하지 않는다 — ablation이 실패로 센다


def write_report(question, notes):
    got = [n for n in notes if not g.irrelevant(n["메모"])]
    if not got:                       # 팀 조사관과 같은 가드 — 재료 없이 쓰게 하지 않는다
        return question, ""
    memo = "\n\n".join(f"[자료 «{g.CHUNK_DOC[n['청크']]}» · 청크 {n['청크'].rsplit('#', 1)[-1]}]\n{n['메모']}" for n in got)
    titles = "\n".join(f"«{d}»" for d in dict.fromkeys(g.CHUNK_DOC[n["청크"]] for n in got))
    prompt = f"""질문: {question}

아래 메모만 근거로 이 질문에 답하는 보고서를 써라.
- 내용 단위(작품·트랙·규정 항목 등)로 소제목(## )을 나눠라. 머리말과 맺음말을 포함해 25~45문장.
- 메모에 없는 사실은 쓰지 마라. 읽지 않은 구간에 대해서는 '없다'고 단정하지 말고 '확인하지 못했다'고 적어라.
{g.cite_rules(got)}- 규정 조항과 실제 트랙 사례를 맞대어 맞는지·어긋나는지를 적어라.

인용할 수 있는 자료:
{titles or "(없음)"}

{g.stats_block(sorted(g.seen_docs(got)))}메모:
{memo or "(관련 메모 없음)"}

첫 줄은 '# 제목', 그다음 마크다운 본문만 답하라."""
    # 긴 보고서를 JSON 안에 넣게 하면 깨졌다(JSONDecodeError) — 대조군만 평문 마크다운으로 받는다
    text = g.ask(prompt, "coord").strip()
    first, _, rest = text.partition("\n")
    return (first.lstrip("# ").strip(), rest.strip()) if first.startswith("#") else (question, text)


def run(question, qid="custom", budget=None, tag="대조군", quiet=False, keep=True, on_step=None):
    """on_step: 팀(graph.run)과 같은 모양의 진행 알림 — 청크 하나 읽을 때마다 ("읽기", [사건]), 끝나면 ("evaluate", [요약])."""
    for k in g.COST:
        g.COST[k] = 0
    budget = budget or g.설정["절수"] * (g.설정["절예산"] + g.설정["기준예산"])
    seeds, refs = pick_start(question)
    t = {"절": "혼자 조사", "역할": "혼자", "시작문서": seeds, "기준자료": refs, "지시": "질문 전체에 답하라",
         "피하기": [], "번호": 0, "바퀴": 1, "예산": budget}
    read, notes = [], []
    for step in range(budget):
        todo = [c for d in seeds for c in g._chunks_of(d) if c not in read]
        if step == 0 and todo:
            cid = todo[0]
        else:
            cands = g.frontier(t, read, [])
            if not cands:
                break
            cid = g.pick_next(t, question, notes, cands)
        memo, chk = g._read_one(cid, t, question, notes)      # 메모 검사(M·P)도 팀과 같은 도구
        notes.append({"청크": cid, "메모": memo, "짝": g.pair_seen(cid, t), **({"대조": chk} if chk else {})})
        read.append(cid)
        if on_step:
            on_step("읽기", [{"절": "혼자 조사", "바퀴": 1, "읽음": len(read), "예산": budget, "청크": cid,
                              "관련없음": g.irrelevant(memo), "되물음": bool(chk)}])
    title, body = write_report(question, notes)
    qfix = None
    if g.설정["스위치"]["인용대조"] and body:                # 집필 인용문 대조(B·B+)도 팀과 같은 도구
        body, qfix = g.check_quotes(t, question, body, notes)
    cites = g.citations(body)
    read_docs = g.seen_docs(notes)
    sec = {"절": "혼자 조사", "번호": 0, "바퀴": 1, "원고": body, "읽은청크": read, "새로읽은": read, "메모": notes,
           "인용": cites, "허위인용": sorted({c for c, _ in cites if c not in read_docs}), "충분": True, "부족": "",
           "지시": t["지시"], **({"인용대조": qfix} if qfix else {})}
    total = g.COST["coord_chars"] + g.COST["sub_chars"]
    g.COST["coord_chars"] = g.COST["sub_chars"] = total          # 위아래가 없다 → 격리율 100%
    report = (f"# {title}\n\n> 질문: {question}\n\n{body}\n\n## 부록: 읽은 자료\n\n"
              + ", ".join(f"`{c}`" for c in read) + "\n")
    s = {"question": question, "report": report, "visited": [(0, c, 1) for c in read],
         "plan": {"목차": [{k: v for k, v in t.items() if k != "피하기"}], "채택": {"0": sec}, "예산기록": [budget],
                  "되돌림": [], "재위임기록": [], "바퀴": 1, "종료": "대조군"}}
    import metrics
    s["metrics"] = metrics.compute(s, g.COST, g)
    if on_step:
        on_step("evaluate", ["⑥ 평가   " + metrics.summary(s["metrics"])])
    if not quiet:
        print(f"대조군   출발 {len(seeds)}건 · 기준 {len(refs)}건 · 예산 {budget}청크 → {len(read)}청크 읽음 · 보고서 {len(report):,}자")
        print("⑥ 평가   " + metrics.summary(s["metrics"]))
    if keep:
        s["run"] = g.save(s, qid, tag)
    return s


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("q", nargs="?", default="s02" if g.SAMPLE else "q03")
    ap.add_argument("--sample", action="store_true", help="예시 코퍼스로(graph를 불러올 때 이미 반영됨)")
    ap.add_argument("--budget", type=int, default=0)
    ap.add_argument("--tag", default="대조군")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    qid = a.q if a.q in g.QUESTIONS else "custom"
    q = g.QUESTIONS[a.q]["question"] if a.q in g.QUESTIONS else a.q
    out = run(q, qid, a.budget or None, a.tag, keep=not a.no_save)
    if out.get("run"):
        print(f"저장: {g.out_dir()}/reports/{out['run']}.md")
