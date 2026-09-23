# -*- coding: utf-8 -*-
"""정답표도 판정 모델도 없이 재는 지표. 만들어진 글(원고·보고서)과 실제로 읽은 청크만 본다.

지표는 두 종류다.
- 경보(0이어야 함): 하나라도 나오면 그 실행은 명백한 실패. 순위 매기기용이 아니다.
- 견줌(높낮이): 설정끼리 비교할 때만 뜻이 있다. 한 번 돌린 값으로 단정하지 않는다(시행마다 흔들림).

각 지표가 어느 장치를 보는 신호인지 `SPEC`에 적어 둔다. graph 모듈을 인자로 받는다
(`import graph`를 하면 `python graph.py`로 돌 때 모듈이 두 번 올라가 스위치 설정이 갈린다).
"""

SPEC = {
    # 이름: (종류, 보는 장치, 한 줄 설명)
    "허위인용": ("경보", "③ 조사관·⑤ 종합", "원고(와 맺음말)가 «»로 인용했는데 읽지도 짝으로 보지도 않은(또는 없는) 문서 수"),
    "범위밖큐": ("경보", "③ 조사관", "'«트랙» 큐 N'의 N이 그 절이 읽은 청크 범위에도, 맞대기 보기로 본 짝 큐에도 없는 인용 수"),
    "무근거절": ("경보", "③ 조사관", "유효 인용이 0개인 절 수 — 자료 없이 쓴 절"),
    "무효배정": ("경보", "① 기획·배정검사", "목차에 남은 없는 제목 수 — 조사관이 빈손으로 출발"),
    "격리율": ("견줌", "②③ 격리", "코디네이터 입력 글자 ÷ 조사관 입력 글자(%) — 낮을수록 원문이 아래에 남음"),
    "중복률": ("견줌", "② 남의구역", "맡은 자료 읽기 중 다른 절도 읽은 청크의 비율(%) — 기준자료 공유 읽기는 뺌"),
    "규정대조율": ("견줌", "① 기준자료·③ 조사관", "트랙을 읽은 절 중 규정 청크도 한 개 이상 읽은 절의 비율(%)"),
    "트랙도달률": ("견줌", "① 기획", "질문이 부른 트랙 중 누군가 한 청크라도 읽은 비율(%)"),
    "읽고안쓴문서": ("견줌", "③ 조사관·④ 점검", "관련 메모가 나왔는데 원고에서 한 번도 인용 안 한 문서의 비율(%)"),
    "인용밀도": ("견줌", "③ 조사관", "절 원고 1,000자당 유효 인용 수"),
    "인용문일치율": ("견줌", "③ 조사관", "큐 번호 하나와 따옴표 인용이 있는 문장 중 인용문이 실제 그 큐 본문에 있는 비율(%)"),
    "인용고침": ("견줌", "③ 인용대조", "원고에서 코드가 틀린 인용으로 잡아 다시 쓰게(또는 지우게) 한 문장 수 — 인용대조를 끄면 0"),
    "메모고침": ("견줌", "③ 인용대조", "메모가 없는 큐·안 본 짝을 적었거나 보여 준 강제 자막 짝을 빠뜨려 다시 물은 청크 수"),
    "예산소진율": ("견줌", "공정성", "새로 읽은 청크 ÷ 받은 예산(%) — 대조군과 비교할 때 둘 다 100% 근처여야 공정"),
    "재위임절": ("견줌", "④ 점검", "재위임된 절 수 — 0이 계속되면 루프가 있으나 마나"),
    "재위임새청크": ("견줌", "④ 점검", "2바퀴 이후 새로 읽은 청크 수 — 0이면 후보가 막힌 것"),
    "되돌림": ("견줌", "④ 점검", "재작성본의 인용이 줄어 지난 원고를 지킨 절 수"),
}


import re

QUOTE = re.compile(r"\"([^\"]{2,80})\"|“([^”]{2,80})”|‘([^’]{2,80})’|「([^」]{2,80})」|(?<![A-Za-z])'((?:[^']|(?<=[A-Za-z])'(?=[A-Za-z])){2,80}?)'(?![A-Za-z])")
CUE_N = re.compile(r"큐\s*(\d+)")
TRACK_CITE = re.compile(r"«([^»]+)»")


def _norm(s):
    s = re.sub(r"\{\\an\d\}|[\u202a\u202c]", "", s)
    return re.sub(r"[\s/\-–—.,!?…·]", "", s)


def quote_check(text, read_tracks, g):
    """'«트랙» 큐 N ... "인용문"' — 한 문장에 큐 번호가 하나, 따옴표 인용이 하나 이상이면
    그 인용문(공백·문장부호 무시)이 실제 큐 N의 본문에 들어 있는지 본다. 트랙은 문장 안 «» 중 트랙인 것,
    없으면 이 절이 읽은 트랙이 하나일 때만 그 트랙. 판단이 모호한 문장은 세지 않는다.
    범위밖큐는 번호가 읽은 범위 안이면 통과시키는데, 번호는 맞고 내용이 틀린 인용(q03 큐 162 '[음산한 음악]' ↔ 실제
    '- 근데 / - [진경] 아!')이 많아서 만든 지표. 번역·요약한 인용은 불일치로 셀 수 있어 경보가 아니라 견줌."""
    checked = matched = 0
    for sent in re.split(r"(?<=[.다])\s+", text):
        cues = CUE_N.findall(sent)
        quotes = [next(x for x in grp if x) for grp in QUOTE.findall(sent)]   # 따옴표 종류별로 짝을 맞춤(영어 아포스트로피에 안 깨지게)
        if len(set(cues)) != 1 or not quotes:
            continue
        tracks = [t for t in TRACK_CITE.findall(sent) if t in g.CUES]
        tracks = list(dict.fromkeys(tracks)) or (list(read_tracks) if len(read_tracks) == 1 else [])
        if len(tracks) != 1:
            continue
        body = next((c[3] for c in g.CUES[tracks[0]] if c[0] == int(cues[0])), None)
        if body is None:
            continue
        checked += 1
        matched += any(_norm(q) and _norm(q) in _norm(body) for q in quotes)
    return checked, matched


BRACKET = re.compile(r"\[([^\[\]]{1,40})\]")
# 문장 나누기 — 한 줄 안에서 마침표·물음표 뒤 공백에서만 자른다('모두 다 읽었다'의 '다 '에서 자르지 않게).
# «넷플릭스 한국어 스타일 가이드 II. SDH»처럼 «» 안의 마침표에서는 자르지 않는다
SENT = re.compile(r"(?<=[.?!。])[ \t]+(?![^«\n]*»)")
CUE_RANGE = re.compile(r"큐\s*\d+\s*[~\-–,]\s*\d+")
LONG_SENT = 300
# 한 글자 따옴표("네")는 QUOTE(2자 이상)가 못 잡고 그 사이 글을 인용으로 잡는다 — 미리 지운다
TINY_QUOTE = re.compile(r"\"[^\"]?\"|“[^”]?”|‘[^’]?’|「[^」]?」|'[^']?'")
TAGS = re.compile(r"\[[^\]]*\]")
# '[화자] 형식으로 표기했다'처럼 표기 방식을 가리키는 [ ]는 인용문이 아니다
GENERIC = {"화자", "화자명", "화자이름", "이름", "효과음", "음악", "소리", "효과", "음향", "효과음악", "노래", "배경음악"}


def sentences(text):
    """SENT로 자르되 따옴표가 열린 채면 다음 조각과 잇는다('... to go. Okay.'를 인용한 문장이 둘로 갈렸다).
    조각은 원문의 부분 문자열 그대로 — 틀린 문장을 원고에서 바꿔 끼울 때 쓴다.
    줄바꿈에서는 늘 자르고(따옴표가 짝이 안 맞아도 그 줄에서 끝남), 소제목(#) 줄은 뺀다 — 소제목이 문장에 붙어 통째로 지워지지 않게."""
    out = []
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        start = 0
        for m in SENT.finditer(line):
            seg = line[start:m.start()]
            if seg.count('"') % 2 == 0 and seg.count("“") <= seg.count("”") and seg.count("「") <= seg.count("」"):
                out.append(seg)
                start = m.end()
        out.append(line[start:])
    return [s for s in out if s.strip()]


def _in(q, body):
    """인용문이 본문에 있나 — 화자·효과음 [ ]를 빼고 옮긴 인용도 인정한다."""
    return _norm(q) in _norm(body) or _norm(q) in _norm(TAGS.sub("", body))


CITE_CUES = re.compile(r"«([^»]+)»\s*(?:의\s*)?큐\s*(\d+)")


def quote_issues(text, read_tracks, pool, g, seen_cue=None):
    """③ 인용대조(도구) — 틀린 인용 문장을 [(문장, 종류, 설명)]으로 돌려준다. 조사관이 이 문장만 다시 쓴다.
    - 큐불일치·없는큐(B): 한 문장에 큐 번호 하나 + 트랙 하나 + 따옴표나 [ ] 인용 → 인용문이 그 큐 본문에 있어야
      (지표 quote_check와 같은 규칙에 [ ]를 더함 — q03 큐 162 '[음산한 음악]' ↔ 실제 '- 근데 / - [진경] 아!')
    - 출처없음(B+): 큐 번호로 못 가린 문장의 따옴표 인용 → 읽은 청크·본 짝 큐 어디엔가 있어야
      (q10 번역문 창작: 큐 번호 없이 'Why do we even hike?'를 지어냄). 규정만 인용한 문장은 건너뜀(영어 규정을 옮긴 말일 수 있다)
    pool = 읽은 청크 원문 + 본 짝 큐 본문을 _norm한 문자열([ ]를 뺀 판도 이어 붙임).
    작품·문서 이름을 따옴표로 쓴 것('아파트 E09')은 인용문이 아니라 건너뛴다.
    - 안읽은큐: seen_cue(문서, 큐)를 주면 '«트랙» 큐 N'이 읽은 범위·본 짝 밖인 문장도 잡는다(경보 범위밖큐를 쓰기 전에 막음)."""
    names = {_norm(x) for x in list(g.DOCS) + [m.get("work", "") for m in g.META.values()] if x}
    out = []
    for sent in sentences(text):
        if len(sent) > LONG_SENT:          # 문장 나누기가 실패한 덩어리일 수 있다 — 통째로 지우지 않게 손대지 않는다
            continue
        # 안읽은큐: '«트랙» 큐 N'의 N을 읽지도 짝으로 보지도 않았다(경보 범위밖큐와 같은 기준) — 인용문이 없어도 잡는다
        if seen_cue:
            unseen = [(t, int(n)) for t, n in CITE_CUES.findall(sent)
                      if re.sub(r"\s*#\d+/\d+$", "", t.strip()) in g.CUES
                      and not seen_cue(re.sub(r"\s*#\d+/\d+$", "", t.strip()), int(n))]
            if unseen:
                out.append((sent, "안읽은큐", "읽지 않은 구간의 큐다: " + ", ".join(f"«{t}» 큐 {n}" for t, n in unseen)
                            + " — 메모에 있는 큐로 바꾸거나 그 사실을 빼라"))
                continue
        quotes = [next(x for x in grp if x) for grp in QUOTE.findall(TINY_QUOTE.sub("", sent))]
        cues = set(CUE_N.findall(sent))
        cites = TRACK_CITE.findall(sent)
        # «» 인용이 아예 없는 문장만 이 절이 읽은 트랙(하나일 때)으로 본다 — 규정만 인용한 문장의 '큐 N'은 어느 트랙인지 모른다
        tracks = list(dict.fromkeys(t for t in cites if t in g.CUES)) or (
            list(read_tracks) if len(read_tracks) == 1 and not cites else [])
        marks = [m for m in quotes + [b for b in BRACKET.findall(sent) if _norm(b) not in GENERIC] if _norm(m)]
        # '큐 3~9'·'큐 3, 5'처럼 범위·나열이면 어느 큐 본문과 견줄지 모른다 → 큐 대조는 건너뛰고 출처 검사(B+)만
        if len(cues) == 1 and len(tracks) == 1 and marks and not CUE_RANGE.search(sent):
            n = int(next(iter(cues)))
            body = next((c[3] for c in g.CUES[tracks[0]] if c[0] == n), None)
            if body is None:
                out.append((sent, "없는큐", f"«{tracks[0]}»에는 큐 {n}이 없다"))
            elif not any(_in(m, body) for m in marks):
                out.append((sent, "큐불일치", f"«{tracks[0]}» 큐 {n}의 실제 본문: {body}"))
            continue
        if cites and not any(t in g.CUES for t in cites):
            continue
        for q in quotes:
            if any(n.startswith(_norm(q)) for n in names):      # 작품·문서 이름을 따옴표로 쓴 것
                continue
            if len(_norm(q)) >= 3 and _norm(q) not in pool:
                out.append((sent, "출처없음", f"'{q}'는 읽은 원문·짝 큐 어디에도 없다"))
                break
    return out


def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def compute(s, cost, g):
    p = s["plan"]
    secs = [v for _, v in sorted(((int(k), v) for k, v in p["채택"].items()))]
    visited = [(int(i), c, int(r)) for i, c, r in s.get("visited", [])]

    false_cites = out_of_range = cue_cites = no_ground = valid_total = 0
    unused = used_pool = 0
    rule_ok = track_secs = 0
    q_checked = q_matched = 0
    for sec in secs:
        read = sec["읽은청크"]
        read_docs = g.seen_docs(sec["메모"]) | {g.CHUNK_DOC[c] for c in read}   # 짝 트랙(맞대기 보기로 본 것) 포함
        pair_cues = {(d, n) for x in sec["메모"] for d, n in x.get("짝", [])}
        cites = [tuple(x) for x in sec["인용"]]
        bad = [t for t, _ in cites if t not in read_docs]
        false_cites += len(set(bad))
        valid = [(t, n) for t, n in cites if t in read_docs]
        valid_total += len(valid)
        no_ground += not valid
        for t, n in valid:
            if n is not None and t in g.DOCS and g.META[t]["type"] == "track":
                cue_cites += 1
                spans = [g.CHUNK_CUES[c] for c in read if g.CHUNK_DOC[c] == t]
                out_of_range += not (any(a <= n <= b for a, b in spans) or (t, n) in pair_cues)
        useful = {g.CHUNK_DOC[x["청크"]] for x in sec["메모"] if not g.irrelevant(x["메모"])}
        cited = {t for t, _ in valid}
        used_pool += len(useful)
        unused += len(useful - cited)
        tracks_read = {g.CHUNK_DOC[c] for c in read if c in g.CHUNK_TIME}
        a_, b_ = quote_check(sec["원고"], tracks_read, g)
        q_checked += a_
        q_matched += b_
        kinds = {g.META[d]["type"] for d in read_docs}
        if "track" in kinds:
            track_secs += 1
            rule_ok += "rule" in kinds

    # 중복률: 절마다 기준자료 문서 청크는 빼고(공유가 정상) 맡은 읽기끼리만 견준다
    toc = p["목차"]
    shared = [{c for r in t.get("기준자료", []) for c in g._chunks_of(r)} for t in toc]
    own_reads = [(i, c) for i, c, _ in visited if i < len(toc) and c not in shared[i]]
    readers = {}
    for i, c in own_reads:
        readers.setdefault(c, set()).add(i)
    dup = sum(1 for i, c in own_reads if len(readers[c]) > 1)

    named = {m["work"] for m in g.META.values() if m["type"] == "track" and m["work"] in s["question"]}
    asked = g.asked_tracks(s["question"], named)
    read_any = {g.CHUNK_DOC[c] for _, c, _ in visited}

    invalid = [d for t in toc for d in list(t["시작문서"]) + list(t.get("기준자료", []))
               if d not in g.DOCS and d not in g.CHUNKS]
    budget = sum(p.get("예산기록", []))
    body_chars = sum(len(sec["원고"]) for sec in secs)

    return {
        "허위인용": false_cites + len(p.get("맺음말허위인용", [])),
        "범위밖큐": out_of_range,
        "큐인용": cue_cites,
        "무근거절": no_ground,
        "무효배정": len(invalid),
        "격리율": _pct(cost["coord_chars"], cost["sub_chars"]),
        "중복률": _pct(dup, len(own_reads)),
        "규정대조율": _pct(rule_ok, track_secs),
        "트랙도달률": _pct(len(asked & read_any), len(asked)) if asked else None,
        "읽고안쓴문서": _pct(unused, used_pool),
        "인용문일치율": _pct(q_matched, q_checked) if q_checked else None,
        "인용문검사": q_checked,
        "인용밀도": round(1000 * valid_total / body_chars, 2) if body_chars else 0.0,
        "인용고침": sum(sec.get("인용대조", {}).get("고침", 0) + sec.get("인용대조", {}).get("지움", 0) for sec in secs),
        # 재위임 절은 지난 바퀴 메모를 이어받으니 청크별로 한 번만 센다
        "메모고침": len({x["청크"] for sec in secs for x in sec["메모"] if x.get("대조")}),
        "예산소진율": _pct(len(visited), budget),
        "재위임절": len(p.get("재위임기록", [])),
        "재위임새청크": sum(1 for *_, r in visited if r > 1),
        "되돌림": len(p.get("되돌림", [])),
        "절수": len(secs),
        "읽은청크": len(visited),
        "보고서글자": len(s.get("report", "")),
        "호출": cost["calls"],
        "재질문": cost.get("retry", 0),
        "JSON실패": cost.get("json_fail", 0),
        "대조질문": cost.get("check_ask", 0),
        "코디네이터글자": cost["coord_chars"],
        "조사관글자": cost["sub_chars"],
    }


def summary(m):
    alarms = [k for k, (kind, _, _) in SPEC.items() if kind == "경보" and m.get(k)]
    head = "경보 " + (", ".join(f"{k} {m[k]}" for k in alarms) if alarms else "0")
    keys = ["격리율", "중복률", "규정대조율", "트랙도달률", "인용밀도", "예산소진율", "재위임절"]
    return head + " | " + " · ".join(f"{k} {m[k]}" for k in keys) + f" | 호출 {m['호출']}"
