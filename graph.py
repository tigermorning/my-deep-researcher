# -*- coding: utf-8 -*-
"""자막 규정·트랙 딥리서처 — 기획 → 배치 → 조사관(병렬) → 점검(루프) → 종합 → 평가.

    python graph.py q03              # questions.json의 질문 id
    python graph.py "질문 원문"

코퍼스는 scripts/build_corpus.py가 만든 data/corpus.json(로컬 전용)을 읽는다.
"""
import json
import operator
import os
import re
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

ROOT = Path(__file__).resolve().parent
설정 = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 코퍼스 · 청크
CORPUS = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
DOCS, META, LINKS = CORPUS["docs"], CORPUS["meta"], CORPUS["links"]


def _pieces(text, limit, is_track):
    """문서를 limit자 이하 조각으로 자른다. 트랙은 큐 줄 경계, 규정은 제목(#) 경계를 우선한다."""
    lines = text.split("\n")
    head = lines[0] + "\n" if is_track else ""
    body = lines[1:] if is_track else lines
    out, cur = [], []
    size = 0
    for line in body:
        boundary = is_track or line.startswith("#")
        if cur and size + len(line) + 1 > limit and (boundary or size > limit * 1.5):
            out.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out.append(cur)
    return [head + "\n".join(p) for p in out]


def _track_span(piece):
    cues = [l.split("\t") for l in piece.split("\n")[1:] if l.count("\t") >= 2]
    if not cues:
        return ""
    a, b = cues[0], cues[-1]
    return f"큐 {a[0]}~{b[0]}, {a[1].split(' --> ')[0][:8]}~{b[1].split(' --> ')[1][:8]}"


CHUNKS, DOC_CHUNKS, CHUNK_LABEL = {}, {}, {}
for _t, _text in DOCS.items():
    _is_track = META[_t]["type"] == "track"
    _ps = _pieces(_text, 설정["청크글자"], _is_track)
    DOC_CHUNKS[_t] = []
    for _n, _p in enumerate(_ps, 1):
        cid = f"{_t} #{_n}/{len(_ps)}"
        CHUNKS[cid] = _p
        CHUNK_LABEL[cid] = _track_span(_p) if _is_track else ""
        DOC_CHUNKS[_t].append(cid)
CHUNK_DOC = {c: t for t, cs in DOC_CHUNKS.items() for c in cs}

QUESTIONS = {q["id"]: q for q in json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))["questions"]}

# ---------------------------------------------------------------- 비용 카운터
COST = {"calls": 0, "coord_chars": 0, "sub_chars": 0}


# ---------------------------------------------------------------- LLM 호출
def _load_key():
    if os.environ.get("OPENAI_API_KEY"):
        return
    for f in [ROOT / ".env", Path.home() / "Documents" / "openai_key.env"]:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
                    return


_load_key()
assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY가 없다 — 환경변수나 .env에 넣을 것"

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError  # noqa: E402

_client = OpenAI()
일시적오류 = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def ask(prompt, who, as_json=False, temperature=0):
    """who = "coord"(코디네이터) | "sub"(조사관). 보낸 글자 수를 따로 센다 — 격리율의 재료."""
    import time
    COST["calls"] += 1
    COST[f"{who}_chars"] += len(prompt)
    kw = {"response_format": {"type": "json_object"}} if as_json else {}
    for attempt in range(5):
        try:
            r = _client.chat.completions.create(
                model=설정["모델"], temperature=temperature,
                messages=[{"role": "user", "content": prompt}], **kw)
            text = r.choices[0].message.content
            return json.loads(text) if as_json else text
        except 일시적오류:
            time.sleep(2 ** attempt)
    raise RuntimeError("OpenAI 호출 5번 연속 실패")


# ---------------------------------------------------------------- State
class State(TypedDict, total=False):
    question: str
    plan: dict                                   # 목차 · 배치(이번 바퀴에 보낼 절 번호) · 바퀴 · 종료
    sections: Annotated[list, operator.add]      # 조사관 원고 (재위임되면 같은 절이 여러 벌 쌓임)
    visited: Annotated[list, operator.add]       # (절, 청크) — 누가 무엇을 읽었나
    report: str
    metrics: dict
    log: Annotated[list, operator.add]
    task: dict                                   # Send로 조사관 한 명에게만 가는 지시
    prior: dict                                  # 재위임 때 그 절의 지난 원고


# ---------------------------------------------------------------- 노드 (빈 뼈대)
def card(title):
    """기획용 카드. 규정은 제목 + 본문 앞부분, 트랙은 메타 한 줄(앞부분은 타임코드뿐이라 쓸모없음)."""
    m = META[title]
    if m["type"] == "track":
        return (f"- «{title}» [트랙] {DOCS[title].split(chr(10), 1)[0]} "
                f"큐 {m['cues']}개 · {len(DOCS[title]):,}자 · 청크 {len(DOC_CHUNKS[title])}개")
    body = re.sub(r"\s+", " ", DOCS[title].split("\n", 4)[-1])[: 설정["카드글자"]]
    return f"- «{title}» [규정·{m['platform']}] {body}"


def _clean(title):
    """모델이 제목에 «»·따옴표를 붙여 내는 경우가 있다 — 형식만 벗긴다(내용은 안 고친다)."""
    return str(title).strip().strip("«»\"'「」").strip()


def _doc_of(seed):
    """시작문서는 문서 제목이거나 청크 id('제목 #2/7')다."""
    return seed if seed in DOCS else CHUNK_DOC[seed]


def _chunks_of(seed):
    return DOC_CHUNKS[seed] if seed in DOCS else [seed]


def _is_track(seed):
    return META[_doc_of(seed)]["type"] == "track"


OPTIONAL_RULES = {"작업자 자료: SDH 효과음 예시", "작업자 자료: 표기·맞춤법·번역", "넷플릭스 스타일 가이드: 일반 요구사항"}


def required_rules(track):
    """트랙 종류별 필수 규정 = 빌드 때 이어 둔 규정 링크 중 보조 자료(OPTIONAL_RULES)를 뺀 것.
    넷플릭스 한국어 SDH → 가이드 II절 / 넷플릭스 강제 자막 → 가이드 I절 + 강제 자막 규정 2건 / 디즈니+·쿠팡 → 작업 기본 원칙"""
    return [r for r in LINKS.get(track, []) if META[r]["type"] == "rule" and r not in OPTIONAL_RULES]


def asked_tracks(question, named):
    """질문이 부른 트랙. 작품 이름이 질문에 있어야 하고,
    - 원문 쪽 트랙(자막 언어 = 작품 원어)은 기준으로 쓰이니 늘 허용
    - 그 밖의 트랙은 트랙 이름 낱말(예: '일본어', '번역')이 전부 질문에 있어야 허용
    - 단, 질문이 그 작품의 트랙을 하나도 특정하지 않으면 그 작품 트랙은 다 허용
    """
    out = set()
    for w in named:
        ts = [t for t, m in META.items() if m["type"] == "track" and m["work"] == w]
        hit = [t for t in ts if all(tok in question for tok in META[t]["track"].split())]
        for t in ts:
            if not hit or t in hit or META[t]["lang"] == META[t]["orig_lang"]:
                out.add(t)
    return out


def check_plan(raw_toc, question):
    """모델이 낸 목차를 코드로 검사한다. 순서가 중요하다.
    1. 제목 정리(«» 벗기기) → 없는 제목은 `무효`, 질문이 부르지 않은 트랙(asked_tracks)은 `질문밖`
    2. 질문에 작품 이름이 없으면 규정 질문 → 1절로 모은다
    3. 같은 자료를 역할만 바꿔 나눈 절은 합친다
       - 제목이 같은 절은 하나로
       - 트랙 절이 있으면 규정만 받은 절은 없애고 그 규정을 트랙 절의 기준자료로 넘긴다
         (규정만 읽는 조사관은 실제 자막을 못 봐서 '규정과 맞나'를 판단할 수 없다)
    4. 시작문서는 절끼리 청크 단위로 겹치면 안 된다
       - 앞 절과 겹치는 트랙은 버리지 않고 이 절의 기준자료(공유 참고)로 옮긴다 — 원문 트랙을 여러 번역 절이 함께 볼 때
       - 자료가 앞 절과 전부 겹치면 = 같은 자료를 역할만 바꿔 나눈 절 → 그 절에 합친다
    5. 절 수 상한 초과분은 가장 가벼운 절에 붙인다 (4 뒤에 — 먼저 하면 줄줄이 합쳐진다)
    6. 기준자료
       - 규정: 같은 작품·같은 언어 트랙의 규정 링크에 있는 것만 (`불일치`로 뺌)
       - 트랙: 같은 작품의 원문 쪽 트랙만 (원문 기준으로 함께 보는 공유 자료). 번역 트랙이 오면 3-3에서 절로 올린다
       - 트랙 종류별 필수 규정이 빠졌으면 채운다 (`필수채움`)
       - 번역 트랙을 맡은 절에 같은 작품·회차의 원문 쪽 트랙이 없으면 채운다 (`필수채움`)
    """
    bad, mismatch, merged, offtopic, filled, promoted = [], [], [], [], [], []
    named = {m["work"] for m in META.values() if m["type"] == "track" and m["work"] in question}
    asked = asked_tracks(question, named)
    secs = []
    for x in raw_toc:
        seeds, refs = [], []
        for key, out in (("시작문서", seeds), ("기준자료", refs)):
            for d in map(_clean, x.get(key, []) or []):
                if d not in DOCS and d not in CHUNKS:
                    bad.append(d)
                elif _is_track(d) and _doc_of(d) not in asked:
                    offtopic.append(d)
                elif key == "기준자료" and not _is_track(d):
                    out.append(d)
                elif key == "기준자료":
                    out.append(_doc_of(d))
                else:
                    out.append(d)
        role = x.get("역할") if x.get("역할") in 설정["역할"] else next(iter(설정["역할"]))
        secs.append({"절": str(x.get("절") or "(제목 없음)"), "역할": role, "시작문서": seeds,
                     "기준자료": refs, "지시": str(x.get("지시", ""))})

    # 2) 작품 이름 없는 질문 = 규정 질문 → 1절
    if not named and len(secs) > 1:
        merged += [sec["절"] for sec in secs[1:]]
        secs = [{"절": "규정 조사", "역할": "규정 담당",
                 "시작문서": list(dict.fromkeys(d for sec in secs for d in sec["시작문서"])),
                 "기준자료": [r for sec in secs for r in sec["기준자료"]],
                 "지시": " ".join(dict.fromkeys(sec["지시"] for sec in secs if sec["지시"]))}]

    # 3-1) 같은 제목 절 합치기
    by_name = {}
    for sec in secs:
        m = by_name.get(sec["절"])
        if m is None:
            by_name[sec["절"]] = sec
            continue
        m["시작문서"] += [d for d in sec["시작문서"] if d not in m["시작문서"]]
        m["기준자료"] += sec["기준자료"]
        m["지시"] = f"{m['지시']} {sec['지시']}".strip()
        merged.append(sec["절"])
    secs = list(by_name.values())

    # 3-2) 규정만 맡은 절 → 트랙 절의 기준자료로
    if any(any(map(_is_track, sec["시작문서"])) for sec in secs):
        keep, orphan = [], []
        for sec in secs:
            if any(map(_is_track, sec["시작문서"])):
                keep.append(sec)
            else:
                orphan += [_doc_of(d) for d in sec["시작문서"]] + sec["기준자료"]
                merged.append(sec["절"])
        for sec in keep:
            sec["기준자료"] += orphan
        secs = keep

    # 3-3) 기준자료에 둘 수 있는 트랙은 원문 쪽 트랙(자막 언어 = 작품 원어)뿐이다.
    #      번역 트랙이 기준자료에 오면 = 맡아 읽어야 할 자료를 공유 참고로 떠넘긴 것 → 그 트랙을 맡는 절을 새로 만든다
    is_source = lambda t: META[t]["lang"] == META[t]["orig_lang"]
    owned = {_doc_of(d) for sec in secs for d in sec["시작문서"]}
    new_secs = []
    for sec in secs:
        keep_refs = []
        for r in sec["기준자료"]:
            if META[r]["type"] == "track" and not is_source(r):
                if r not in owned:
                    src = [x for x in sec["기준자료"] + [_doc_of(d) for d in sec["시작문서"]]
                           if META[x]["type"] == "track" and is_source(x) and META[x]["work"] == META[r]["work"]]
                    new_secs.append({"절": r, "역할": "대조 담당", "시작문서": [r], "기준자료": list(dict.fromkeys(src)),
                                     "지시": sec["지시"]})
                    owned.add(r)
                    promoted.append(r)
            else:
                keep_refs.append(r)
        sec["기준자료"] = keep_refs
    secs += new_secs

    # 4) 시작문서 겹침(청크 단위)
    kept, owner = [], {}                      # owner: 청크 → 그 청크를 맡은 절
    for sec in secs:
        free = [d for d in sec["시작문서"] if all(c not in owner for c in _chunks_of(d))]
        taken_tracks = [_doc_of(d) for d in sec["시작문서"] if d not in free and _is_track(d)]
        if sec["시작문서"] and not free:     # 전부 겹침 → 역할만 다른 절 → 합침
            host = owner[_chunks_of(sec["시작문서"][0])[0]]
            host["기준자료"] += sec["기준자료"]
            host["지시"] = f"{host['지시']} {sec['지시']}".strip()
            merged.append(sec["절"])
            continue
        if not free:  # 쓸 수 있는 제목이 하나도 없던 절 → 이웃 문서 중 아직 안 잡힌 것으로 대체
            near = [n for k in kept for d in k["시작문서"] for n in LINKS.get(_doc_of(d), [])]
            pool = [d for d in near + list(DOCS) if all(c not in owner for c in DOC_CHUNKS[d])]
            free = [pool[0]]
        sec = {**sec, "시작문서": free, "기준자료": sec["기준자료"] + taken_tracks}
        for d in free:
            for c in _chunks_of(d):
                owner[c] = sec
        kept.append(sec)

    # 5) 절 수 상한 초과분 → 가장 가벼운 절에
    size = lambda sec: sum(len(CHUNKS[c]) for d in sec["시작문서"] for c in _chunks_of(d))
    for extra in kept[설정["절수"]:]:
        host = min(kept[: 설정["절수"]], key=size)
        host["시작문서"] = host["시작문서"] + extra["시작문서"]
        host["기준자료"] = host["기준자료"] + extra["기준자료"]
        merged.append(extra["절"])
    kept = kept[: 설정["절수"]]

    # 6) 기준자료 정리
    planned = {_doc_of(d) for sec in kept for d in sec["시작문서"] if _is_track(d)}
    toc = []
    for sec in kept:
        own = [_doc_of(d) for d in sec["시작문서"] if _is_track(d)]
        mine = {(META[t]["work"], META[t]["lang"]) for t in own}
        works = {w for w, _ in mine}
        refs = list(dict.fromkeys(r for r in sec["기준자료"] if r not in own))
        rules = [r for r in refs if META[r]["type"] == "rule"]
        ref_tracks = [r for r in refs if META[r]["type"] == "track" and META[r]["work"] in works]
        if mine:
            fit = {r for t in planned if (META[t]["work"], META[t]["lang"]) in mine
                   for r in LINKS.get(t, []) if META[r]["type"] == "rule"}
            mismatch += [r for r in rules if r not in fit]
            rules = [r for r in rules if r in fit]
            for t in own:
                for r in required_rules(t):
                    if r not in rules:
                        rules.append(r)
                        filled.append(r)
                # 번역 트랙이면 같은 작품·같은 회차의 원문 쪽 트랙(질문이 부른 것)을 기준자료로 채운다
                if META[t]["lang"] != META[t]["orig_lang"]:
                    for src in sorted(asked):
                        m = META[src]
                        if (m["work"], m["ep"]) == (META[t]["work"], META[t]["ep"]) and m["lang"] == m["orig_lang"] \
                                and src not in own and src not in ref_tracks:
                            ref_tracks.append(src)
                            filled.append(src)
        toc.append({"절": sec["절"], "역할": sec["역할"], "시작문서": sec["시작문서"],
                    "기준자료": rules + ref_tracks, "예산": 설정["절예산"], "지시": sec["지시"]})
    return toc, {"무효배정": bad, "규정불일치": mismatch, "합친절": merged, "질문밖트랙": offtopic, "필수채움": filled,
                 "절로승격": promoted}


def plan(s):
    q = s["question"]
    roster = "\n".join(f"- {k}: {v}" for k, v in 설정["역할"].items())
    cards = "\n".join(card(t) for t in DOCS)
    prompt = f"""너는 자막 규정 조사팀의 코디네이터다. 아래 질문에 답할 보고서의 목차를 짜고, 절마다 조사관 한 명을 붙인다.

질문: {q}

먼저 판단하라: 질문에 작품 이름이 나오는가?
- 안 나오고 규정의 기준(수치·정의)만 묻는다 → 1절만 만든다. 시작문서는 규정 문서, 트랙은 넣지 않는다. 아래 규칙 중 트랙 관련 규칙은 무시한다.
- 나온다 → 아래 규칙대로 나눈다.

규칙
- 목차는 반드시 내용 단위로 나눠라(작품별·플랫폼별·언어별·규정 항목별 등). '개요·배경·분석·결론' 같은 형식 단위로 나누지 마라.
- 절은 1~{설정['절수']}개.
  - 자막 트랙을 둘 이상 읽어야 하면 트랙(또는 작품·언어·플랫폼)마다 절을 나눠라.
  - 같은 자료를 역할(관점)만 바꿔 여러 절로 나누지 마라. 한 사람이 자료를 읽으며 여러 관점을 함께 적용하는 편이 낫다.
  - 질문이 맞대 보라고 하는 트랙 쌍(같은 회차의 강제 자막과 SDH·CC, 번역과 그 원문 트랙)은 한 절의 시작문서에 함께 넣어라. 갈라 놓으면 맞대는 사람이 없다.
  - 여러 절의 결과를 비교·종합하는 절은 만들지 마라. 종합은 보고서를 이어 붙이는 단계에서 한다.
  - 트랙 하나가 커서 나눠야 하면 청크 구간으로 나눠라. 시작문서에 '제목 #1/7'처럼 청크 번호를 적으면 그 청크만 맡긴다.
- 절마다 역할 하나를 명단에서 고른다.
- 시작문서: 그 절이 맡아 읽을 자료 1~3건(트랙 또는 트랙의 청크). 절끼리 겹치면 안 된다. 질문에 이름이 나온 트랙은 빠짐없이 어느 한 절의 시작문서나 기준자료에 넣어라. 규정만 시작문서로 주는 절은 만들지 마라 — 규정은 기준자료에 넣는다(규정만 묻는 1절짜리 질문은 예외).
- 기준자료: 그 절이 대조할 자료. 여러 절이 같은 것을 써도 된다.
  - 규정 0~2건: 트랙의 플랫폼·언어·종류(첫 줄 [ ] 안)에 맞는 규정.
  - 원문 트랙: 번역을 비교할 때 여러 절이 함께 봐야 하는 원작 언어 트랙(자막 언어 = 작품 원어). 번역 트랙은 기준자료에 넣지 말고 각자 절을 줘라.
- 제목은 아래 자료 목록의 «» 안 글자 그대로 옮겨라.
- 지시: 그 조사관이 무엇을 찾아야 하는지 한두 문장.

조사관 명단
{roster}

자료 목록
{cards}

JSON으로만 답하라: {{"목차": [{{"절": "...", "역할": "...", "시작문서": ["..."], "기준자료": ["..."], "지시": "..."}}]}}"""
    raw = ask(prompt, "coord", as_json=True).get("목차", [])
    if 설정["스위치"]["배정검사"]:
        toc, fix = check_plan(raw, q)
    else:  # 검사를 끄면 모델이 낸 그대로 — 없는 제목도 그대로 넘어간다
        toc = [{"절": str(x.get("절")), "역할": x.get("역할"), "시작문서": list(x.get("시작문서", [])),
                "기준자료": list(x.get("기준자료", [])), "예산": 설정["절예산"], "지시": str(x.get("지시", ""))}
               for x in raw[: 설정["절수"]]]
        fix = {"무효배정": [d for x in toc for d in x["시작문서"] + x["기준자료"] if d not in DOCS and d not in CHUNKS],
               "규정불일치": [], "합친절": [], "질문밖트랙": [], "필수채움": [], "절로승격": []}
    names = {"무효배정": "없는 제목", "질문밖트랙": "질문 밖 작품 트랙", "규정불일치": "트랙에 안 맞는 규정",
             "필수채움": "채운 필수 규정", "합친절": "합친 절", "절로승격": "기준자료에서 절로 올린 트랙"}
    fixed = [f"{names[k]} {len(v)}" for k, v in fix.items() if v] if 설정["스위치"]["배정검사"] else []
    lines = [f"① 기획   목차 {len(raw)}절 제안 → {len(toc)}절" + (" · 코드가 고침: " + ", ".join(fixed) if fixed else "")]
    lines += [f"          {t['절']} [{t['역할']}] → " + ", ".join(f"«{d}»" for d in t["시작문서"])
              + (" | 기준: " + ", ".join(f"«{d}»" for d in t["기준자료"]) if t["기준자료"] else "") for t in toc]
    return {"plan": {"목차": toc, "배치": list(range(len(toc))), "바퀴": 1, "종료": "", **fix},
            "log": ["\n".join(lines)]}


def dispatch(s):
    idxs = s["plan"]["배치"]
    return {"log": [f"② 배치   서브에이전트 {len(idxs)}명 파견 (빈 노드)"]}


def fanout(s):
    idxs = s["plan"]["배치"]
    if not idxs:
        return "review"
    toc = s["plan"]["목차"]
    return [Send("researcher", {"task": {**toc[i], "번호": i}, "prior": {}}) for i in idxs]


def researcher(s):
    t = s["task"]
    return {"sections": [{"절": t["절"], "번호": t["번호"], "원고": "", "읽은청크": [], "인용": [],
                          "충분": True, "부족": ""}],
            "log": [f"   ③ 조사관   «{t['절']}» 0청크 읽고 0자 (빈 노드)"]}


def review(s):
    n = len(s["plan"]["목차"])
    return {"plan": {**s["plan"], "배치": [], "종료": "빈 노드"},
            "log": [f"④ 점검   {n}절 중 빈 칸 0개 (빈 노드)"]}


def route(s):
    return "dispatch" if s["plan"]["배치"] else "synthesize"


def synthesize(s):
    n = len({x["번호"] for x in s["sections"]})
    return {"report": "", "log": [f"⑤ 종합   {n}절 → 보고서 0자 (빈 노드)"]}


def evaluate(s):
    return {"metrics": {}, "log": ["⑥ 평가   지표 0개 (빈 노드)"]}


# ---------------------------------------------------------------- 그래프
def build():
    g = StateGraph(State)
    for name in ["plan", "dispatch", "researcher", "review", "synthesize", "evaluate"]:
        g.add_node(name, globals()[name])
    g.add_edge(START, "plan")
    g.add_edge("plan", "dispatch")
    g.add_conditional_edges("dispatch", fanout, ["researcher", "review"])
    g.add_edge("researcher", "review")
    g.add_conditional_edges("review", route, ["dispatch", "synthesize"])
    g.add_edge("synthesize", "evaluate")
    g.add_edge("evaluate", END)
    return g.compile()


def run(question):
    for k in COST:
        COST[k] = 0
    out = build().invoke({"question": question}, {"recursion_limit": 50})
    for line in out["log"]:
        print(line)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    arg = sys.argv[1] if len(sys.argv) > 1 else "q03"
    q = QUESTIONS[arg]["question"] if arg in QUESTIONS else arg
    n_chars = sum(len(v) for v in DOCS.values())
    print(f"코퍼스 {len(DOCS)}건 · {n_chars:,}자 · 청크 {len(CHUNKS)}개 (청크당 {설정['청크글자']:,}자 이하)\n")
    print(f"질문: {q}\n")
    run(q)
