# -*- coding: utf-8 -*-
"""자막 규정·트랙 딥리서처 — 기획 → 배치 → 조사관(병렬) → 점검(루프) → 종합 → 평가.

    python graph.py q03              # questions.json의 질문 id
    python graph.py "질문 원문"
    python graph.py s02 --sample     # 공개용 예시 코퍼스(지어낸 자료)로 — DR_SAMPLE=1 과 같다

코퍼스는 scripts/build_corpus.py가 만든 data/corpus.json(로컬 전용)을 읽는다.
예시 모드는 data/sample_corpus.json · data/sample_questions.json을 읽고 output/sample/에 저장한다(본 실험 기록과 섞이지 않게).
"""
import json
import operator
import os
import re
import sys
import threading
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

ROOT = Path(__file__).resolve().parent
설정 = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# 예시 모드: import할 때 코퍼스를 읽으므로(baseline·app도 이 모듈을 씀) 인자 해석 전에 정한다.
# 환경변수로도 남겨 하위 프로세스·다른 모듈이 같은 모드를 보게 한다.
# 주의: sys.argv는 이 모듈을 import한 프로그램의 인자다 — 다른 도구에서 '--sample'을 다른 뜻으로 쓰면 안 된다(app.py도 같은 조건)
SAMPLE = os.environ.get("DR_SAMPLE") == "1" or "--sample" in sys.argv
if SAMPLE:
    os.environ["DR_SAMPLE"] = "1"
CORPUS_FILE = ROOT / "data" / ("sample_corpus.json" if SAMPLE else "corpus.json")
QUESTIONS_FILE = ROOT / "data" / ("sample_questions.json" if SAMPLE else "questions.json")
OUT = ROOT / "output" / "sample" if SAMPLE else ROOT / "output"

# ---------------------------------------------------------------- 코퍼스 · 청크
if SAMPLE and not CORPUS_FILE.exists():
    raise SystemExit(f"{CORPUS_FILE.relative_to(ROOT).as_posix()}이 없다 — python scripts/make_sample_corpus.py 로 다시 만든다")
if not CORPUS_FILE.exists():
    raise SystemExit(
        f"{CORPUS_FILE.relative_to(ROOT).as_posix()}이 없다. 자막·규정 원문은 저작물이라 저장소에 올리지 않았다.\n"
        "- 원본이 있는 PC: python scripts/build_corpus.py\n"
        "- 원본이 없으면: 예시 코퍼스(지어낸 자료)로 끝까지 돌려 볼 수 있다: python graph.py s02 --sample\n"
        "  문서 목록·글자 수·links는 data/corpus_index.json, 실행 결과는 output/ 에서 볼 수 있다\n"
        "  (데모 화면은 코퍼스 없이도 뜬다: streamlit run app.py)")
CORPUS = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
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


def _sec(tc):
    h, m, s = tc.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# 트랙 청크 = 큐 번호 범위 · 시간 범위(초) — 같은 시간대 청크 찾기와 인용 검사에 쓴다
# 규정 청크 = 안에 든 제목(#) 몇 개 — 조사관이 후보를 고를 때 보는 이름표
CHUNK_CUES, CHUNK_TIME = {}, {}
for _c, _p in CHUNKS.items():
    if META[CHUNK_DOC[_c]]["type"] == "track":
        _cues = [l.split("\t") for l in _p.split("\n")[1:] if l.count("\t") >= 2]
        CHUNK_CUES[_c] = (int(_cues[0][0]), int(_cues[-1][0]))
        CHUNK_TIME[_c] = (_sec(_cues[0][1].split(" --> ")[0]), _sec(_cues[-1][1].split(" --> ")[1]))
    else:
        _heads = [l.lstrip("# ").strip() for l in _p.split("\n") if l.startswith("#")]
        CHUNK_LABEL[_c] = " / ".join(_heads[:4])[:90]

# 트랙 큐 목록: (번호, 시작 초, 시작 시각 문자열, 본문, 끝 초) — 모델에게 보여 줄 때 번호·시각을 또렷이 붙이고,
# 같은 시간대 다른 트랙 큐를 코드가 맞대어 붙일 때 쓴다(모델이 탭 구분 줄에서 큐 번호를 자주 잘못 읽었다)
CUES = {}
for _t, _text in DOCS.items():
    if META[_t]["type"] == "track":
        CUES[_t] = []
        for _l in _text.split("\n")[1:]:
            _f = _l.split("\t")
            if len(_f) >= 3:
                _st, _en = _f[1].split(" --> ")
                CUES[_t].append((int(_f[0]), _sec(_st), _st[:8], _f[2], _sec(_en)))


def render(cid):
    """청크 원문을 모델에게 보여 줄 모양으로. 트랙은 줄마다 [큐 N | 시각]."""
    if cid not in CHUNK_TIME:
        return CHUNKS[cid]
    doc = CHUNK_DOC[cid]
    a, b = CHUNK_CUES[cid]
    head = CHUNKS[cid].split("\n", 1)[0]
    return head + "\n" + "\n".join(f"[큐 {n} | {st}] {tx}" for n, _, st, tx, _ in CUES[doc] if a <= n <= b)


QUESTIONS = {q["id"]: q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]}

# ---------------------------------------------------------------- 비용 카운터
COST = {"calls": 0, "coord_chars": 0, "sub_chars": 0, "retry": 0, "json_fail": 0, "check_ask": 0}
_cost_lock = threading.Lock()


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
    kw = {"response_format": {"type": "json_object"}} if as_json else {}
    for attempt in range(5):
        with _cost_lock:              # 조사관들이 스레드로 동시에 돈다. 다시 묻는 것도 호출이다
            COST["calls"] += 1
            COST[f"{who}_chars"] += len(prompt)
        try:
            r = _client.chat.completions.create(
                model=설정["모델"], temperature=temperature,
                messages=[{"role": "user", "content": prompt}], **kw)
            text = r.choices[0].message.content
            return json.loads(text) if as_json else text
        except 일시적오류:
            time.sleep(2 ** attempt)
        except json.JSONDecodeError:      # 긴 원고를 JSON으로 받다가 깨질 때가 있다 — 다시 묻는다
            with _cost_lock:
                COST["retry"] += 1
            if attempt == 4:
                with _cost_lock:
                    COST["json_fail"] += 1  # 지표에 남기고 ablation이 그 실행을 뺀다(빈 결과를 정상 실행처럼 평균 내지 않게)
                return {}
    raise RuntimeError("OpenAI 호출 5번 연속 실패")  # 빈 결과로 조용히 이어 가지 않는다 — 그 실행은 저장되지 않는다


# ---------------------------------------------------------------- State
class State(TypedDict, total=False):
    question: str
    plan: dict                                   # 목차 · 배치(이번 바퀴에 보낼 절 번호) · 바퀴 · 종료
    sections: Annotated[list, operator.add]      # 조사관 원고 (재위임되면 같은 절이 여러 벌 쌓임)
    visited: Annotated[list, operator.add]       # (절 번호, 청크, 바퀴) — 누가 언제 무엇을 읽었나
    report: str
    metrics: dict
    log: Annotated[list, operator.add]
    task: dict                                   # Send로 조사관 한 명에게만 가는 지시
    prior: dict                                  # 재위임 때 그 절의 지난 원고


# ---------------------------------------------------------------- ① 기획
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
    """없는 제목이면 빈 목록 — 배정검사를 끄면 없는 제목이 조사관까지 내려온다(빈손으로 출발)."""
    return DOC_CHUNKS.get(seed) or ([seed] if seed in CHUNKS else [])


def _is_track(seed):
    return META[_doc_of(seed)]["type"] == "track"


OPTIONAL_RULES = {"작업자 자료: SDH 효과음 예시", "작업자 자료: 표기·맞춤법·번역", "넷플릭스 스타일 가이드: 일반 요구사항"}
OPTIONAL_RULES |= {t for t, m in META.items() if m.get("보조")}   # 예시 코퍼스는 meta에 '보조'로 표시한다


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
            ok = lambda d: META[d]["type"] == "rule" or d in asked       # 질문이 부르지 않은 트랙으로 채우지 않는다
            # 자기 기준자료(규정만 받은 1절짜리 규정 질문 등) → 이웃 순. 이 순서가 없으면 q01이 절 0개가 됐다
            pool = [d for d in list(dict.fromkeys(sec["기준자료"] + near))
                    if d in DOCS and ok(d) and all(c not in owner for c in DOC_CHUNKS[d])]
            if not pool:
                merged.append(sec["절"])
                continue
            free = [pool[0]]
            filled.append(f"빈 절 대체: {pool[0]}")
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
                    "기준자료": rules + ref_tracks, "예산": 설정["절예산"], "기준예산": 설정["기준예산"],
                    "지시": sec["지시"]})
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
        # «» 벗기기와 목록 모양 맞추기는 형식 정리라 끄지 않는다 — 끄면 이 조건이 검사가 아니라 표기 잡음을 재게 된다
        as_list = lambda v: [_clean(d) for d in (v if isinstance(v, list) else []) if isinstance(d, str)]
        toc = [{"절": str(x.get("절")), "역할": x.get("역할"), "시작문서": as_list(x.get("시작문서")),
                "기준자료": as_list(x.get("기준자료")), "예산": 설정["절예산"], "기준예산": 설정["기준예산"],
                "지시": str(x.get("지시", ""))}
               for x in raw[: 설정["절수"]] if isinstance(x, dict)]
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


# ---------------------------------------------------------------- ② 배치
def _latest(sections):
    """점검 노드가 채택한 원고를 그대로 쓴다(재위임된 절은 여러 벌 — 채택 규칙은 review 참고)."""
    return {int(k): v for k, v in sections.items()}


def dispatch(s):
    """이번 바퀴에 보낼 절마다 '남의 구역'(피하기 목록)과 지난 원고(prior)를 챙긴다.
    남의 구역 = 다른 절의 시작문서 청크 + 지금까지 다른 절이 읽은 청크. 기준자료(규정·원문 트랙)는 공유라 빼지 않는다.
    조사관끼리는 서로 못 본다 — 코디네이터가 아는 것(배정 · 지난 바퀴 읽기 기록)으로 출발 전에 나눌 수밖에 없다."""
    p, toc = s["plan"], s["plan"]["목차"]
    idxs = p["배치"]
    adopted = _latest(p.get("채택", {}))
    avoid = {}
    for i in idxs:
        if 설정["스위치"]["남의구역"]:
            theirs = {c for j, t in enumerate(toc) if j != i for d in t["시작문서"] for c in _chunks_of(d)}
            theirs |= {c for (j, c, _) in s.get("visited", []) if j != i}
            shared = {c for r in toc[i]["기준자료"] for c in _chunks_of(r)}
            mine = {c for d in toc[i]["시작문서"] for c in _chunks_of(d)}   # 남이 기준자료로 읽었어도 내 몫은 내 몫
            avoid[i] = sorted(theirs - shared - mine)
        else:
            avoid[i] = []
    tasks = {i: {**toc[i], "번호": i, "바퀴": p["바퀴"], "피하기": avoid[i]} for i in idxs}
    priors = {i: adopted.get(i, {}) for i in idxs}
    n_avoid = sum(len(v) for v in avoid.values())
    line = (f"② 배치   {p['바퀴']}바퀴 · 서브에이전트 {len(idxs)}명 파견 · 남의 구역 청크 {n_avoid}개"
            + ("" if 설정["스위치"]["남의구역"] else " (스위치 꺼짐)"))
    budget = p.get("예산기록", []) + [t["예산"] + (0 if priors[i] else t.get("기준예산", 0)) for i, t in tasks.items()]
    return {"plan": {**p, "_tasks": tasks, "_priors": priors, "예산기록": budget}, "log": [line]}


def fanout(s):
    idxs = s["plan"]["배치"]
    if not idxs:
        return "review"
    p = s["plan"]
    return [Send("researcher", {"task": p["_tasks"][i], "prior": p["_priors"][i], "question": s["question"]})
            for i in idxs]


# ---------------------------------------------------------------- ③ 조사관
def _same_scene(doc, other):
    a, b = META[doc], META[other]
    return a["type"] == b["type"] == "track" and (a["work"], a["ep"]) == (b["work"], b["ep"])


def _aligned(doc, t_sec):
    """doc에서 t_sec(초)를 품은 청크. 없으면 가장 가까운 청크."""
    return min(DOC_CHUNKS[doc], key=lambda c: 0 if CHUNK_TIME[c][0] <= t_sec <= CHUNK_TIME[c][1]
               else min(abs(CHUNK_TIME[c][0] - t_sec), abs(CHUNK_TIME[c][1] - t_sec)))


SMALL_CUES = 60


def anchors(t, read):
    """큐가 적은 트랙 청크(강제 자막 등)를 읽었으면, 그 큐 시각이 들어 있는 같은 회차 다른 트랙 청크 → 이유.
    강제 자막 3큐가 회차 전체(6분·37분·63분)에 흩어져 있는데 조사관이 SDH를 앞에서부터 차례로 읽어
    37분·63분 구간은 보지도 않고 'SDH에 없다'고 썼다(q11). 짝 구간을 후보 맨 앞에 이유와 함께 놓는다."""
    own = [_doc_of(d) for d in t["시작문서"] if _chunks_of(d)]
    mates = [d for d in own + [r for r in t["기준자료"] if r in DOCS] if d in CUES]
    out = {}
    for c in read:
        if c not in CHUNK_TIME or CHUNK_CUES[c][1] - CHUNK_CUES[c][0] + 1 > SMALL_CUES:
            continue
        doc = CHUNK_DOC[c]
        a, b = CHUNK_CUES[c]
        for n, s, st, _, _ in CUES[doc]:
            if not a <= n <= b:
                continue
            for e in dict.fromkeys(mates):
                if e != doc and _same_scene(doc, e):
                    hit = _aligned(e, s)
                    out.setdefault(hit, []).append(f"«{doc}» 큐 {n}({st})")
    return {k: ", ".join(v[:4]) for k, v in out.items()}


def frontier(t, read, avoid, rules_only=False):
    """다음에 읽을 청크 후보. 코드가 만들고 모델은 이 중에서 고르기만 한다.
    1) 맡은 자료의 안 읽은 청크  2) 방금 읽은 트랙 청크와 **같은 시간대**의 다른 트랙 청크(같은 회차)
    3) 기준자료 청크  4) 읽은 문서의 링크 이웃 — 규정 전부, 트랙은 같은 회차만(질문 밖 작품으로 새지 않게)
    피하기 목록은 빼되, 다 빠지면 피하기를 무시하고, 그래도 없으면 빈 목록(조사 끝)."""
    own = [_doc_of(d) for d in t["시작문서"] if _chunks_of(d)]
    refs = [r for r in t["기준자료"] if r in DOCS]
    cands = list(anchors(t, read))
    cands += [c for d in t["시작문서"] for c in _chunks_of(d)]
    last = next((c for c in reversed(read) if c in CHUNK_TIME), None)
    if last:
        mid = sum(CHUNK_TIME[last]) / 2
        doc = CHUNK_DOC[last]
        for other in own + refs + LINKS.get(doc, []):
            if other != doc and _same_scene(doc, other):
                cands.append(_aligned(other, mid))
    for r in refs:   # 규정은 전 청크, 기준 트랙은 안 읽은 첫 청크(아무 트랙도 안 읽었으면 시간 맞춤으로는 닿지 못한다)
        cands += DOC_CHUNKS[r] if META[r]["type"] == "rule" else [c for c in DOC_CHUNKS[r] if c not in read][:1]
    scene = [CHUNK_DOC[c] for c in read if c in CHUNK_TIME] + [d for d in own if META[d]["type"] == "track"]
    for c in read:
        for n in LINKS.get(CHUNK_DOC[c], []):
            if META[n]["type"] == "rule":
                cands += DOC_CHUNKS[n]
            elif any(_same_scene(n, x) for x in scene):
                cands.append(_aligned(n, sum(CHUNK_TIME[last]) / 2) if last else DOC_CHUNKS[n][0])
    cands = [c for c in dict.fromkeys(cands) if c not in read]
    if rules_only:   # 기준 예산 단계: 25개로 자르기 **전에** 규정만 남긴다(트랙 청크가 많으면 규정이 잘려 나갔다)
        cands = [c for c in cands if c not in CHUNK_TIME] or cands
    free = [c for c in cands if c not in set(avoid)]
    return (free or cands)[:25]


def _cand_line(c, why=""):
    d = CHUNK_DOC[c]
    tag = "트랙" if META[d]["type"] == "track" else "규정"
    return f"- {c} [{tag}] {CHUNK_LABEL[c]}" + (f" ← {why}와 같은 시간대" if why else "")


def _brief(t, question):
    return (f"질문: {question}\n맡은 절: {t['절']}\n역할: {t['역할']} — {설정['역할'].get(t['역할'], '')}\n"
            f"지시: {t['지시']}")


def read_one(cid, t, question, notes=()):
    """청크 하나를 읽고 메모만 돌려준다 — 원문은 이 함수 밖으로 안 나간다(격리 경계).
    지시는 원문 **뒤에** 둔다. '관련 없으면 관련 없음'이 원문 앞에 있으면 gpt-4o-mini가 원문을 읽기도 전에
    '관련 없음'으로 답했다(«넷플릭스 강제 자막 이해하기»를 q11에 3회 연속 '관련 없음'. 같은 지시를 뒤로 옮기자 조항을 뽑음).
    지금까지의 메모를 맥락으로 함께 준다: 트랙 둘을 맞대려면 앞 트랙에서 본 큐의 시각을 알아야 한다.
    단 규정 청크에는 맥락을 주지 않는다(R) — q01 FAQ 메모가 앞 청크의 I.2·I.15를 되풀이해 원고가 '12·9자'를 FAQ 출처로 적었다.
    인용대조가 켜져 있으면 받은 메모를 코드가 원문과 맞춰 보고 한 번씩 되묻는다(check_memo)."""
    memo, _ = _read_one(cid, t, question, notes)
    return memo


def _read_one(cid, t, question, notes=()):
    """read_one의 본체. (메모, 대조 기록 또는 None)"""
    is_track = cid in CHUNK_TIME
    how = ("근거마다 큐 번호와 시작 시각을 반드시 적어라(예: 큐 123 00:12:03 [효과음] 표기)." if is_track
           else "이 자료는 규정이다(영어 원문일 수 있다 — 조항 제목을 질문의 쟁점과 맞춰 보라). 해당 조항의 번호(예: II.8, I.17)와 요구 내용을 적어라.")
    got = [n for n in notes if not irrelevant(n["메모"])] if is_track else []
    ctx = "\n".join(f"- {n['청크']}: {n['메모']}" for n in got)[-2500:]
    view = render_aligned(cid, t)
    # 맞대기 보기가 붙은 청크는 그 자체가 비교 재료다. 이 말이 없으면 모델이 '관련 없음'으로 빠졌다(q10 영어 번역 6청크 전부)
    pair_hint = ("\n- ↔ 줄은 같은 시간의 짝 트랙 큐다. 같은 시각의 원문·번역(또는 강제 자막·SDH) 쌍이 어떻게 다른지, "
                 "짝이 없는 큐(빠지거나 더해진 것)가 이 질문의 재료다." if "↔ «" in view else "")
    ctx_block = f"지금까지 이 절에서 읽은 메모(맞대 볼 때 참고):\n{ctx or '(아직 없음)'}\n\n" if is_track else ""
    prompt = f"""{_brief(t, question)}

{ctx_block}아래는 자료 «{cid}»의 원문이다.

--- 원문 시작 ---
{view}
--- 원문 끝 ---

할 일: 위 원문에서 질문의 재료가 되는 사례·조항을 최대 8개 골라 메모하라. {how}{pair_hint}
- 모든 {"큐를 나열하지 말고 질문에 답하는 데 필요한 사례만. 큐 번호와 시각은 원문의 [큐 N | 시각]을 그대로 옮겨라" if is_track else "조항을 옮기지 말고 질문에 쓰일 조항만"}.
- 원문에 없는 것은 쓰지 마라.
- 재료가 정말 하나도 없을 때만 '관련 없음'이라고만 답하라."""
    memo = ask(prompt, "sub").strip()
    # 짝 줄(↔)이 붙은 청크는 비교 재료가 있는 게 확실하다. 그런데도 '관련 없음'이면 한 번만 다시 묻는다.
    # 같은 프롬프트가 한 번은 사례 8개, 한 번은 '관련 없음'으로 갈렸다(q10 영어 번역 #3/15, temperature 0).
    pairs = view.count("↔ «")
    if pairs and irrelevant(memo):
        with _cost_lock:
            COST["retry"] += 1
        memo = ask(prompt + f"\n\n(이 원문에는 ↔ 짝 줄이 {pairs}개 있다. 그중 질문에 해당하는 쌍을 골라 메모하라.)", "sub").strip()
    if not 설정["스위치"]["인용대조"] or not is_track or irrelevant(memo):
        return memo, None
    return check_memo(memo, cid, t, prompt, notes)


MEMO_REF = re.compile(r"«([^»]+)»\s*큐\s*(\d+)")
MEMO_OWN = re.compile(r"^[\s\-*•\d.)]*큐\s*(\d+)", re.M)


def memo_issues(memo, cid, t, notes=()):
    """메모 검사(M): 메모에 적힌 큐 번호가 이 조사관이 실제로 본 것인가.
    - '«트랙» 큐 N' → 이 청크나 이 절이 앞서 읽은 청크의 큐 범위, 또는 코드가 ↔ 짝으로 보여 준 큐(이번·앞 청크)
    - 줄 머리의 '큐 N'(«»·↔ 없는 줄) → 이 트랙의 읽은 범위이거나 이 청크의 짝 큐 번호
    앞 메모를 맥락으로 주므로 앞 청크의 큐를 다시 적는 것은 정상이다(틀렸다고 지우면 맥락을 준 뜻이 없다).
    q11 아파트 SDH #6/9: 강제 자막 짝은 큐 2 하나뿐인데 메모가 '↔ 강제 자막 큐 3~9'를 지어냈다(강제 자막은 3큐뿐)."""
    doc = CHUNK_DOC[cid]
    a, b = CHUNK_CUES[cid]
    here = pair_hosts(cid, t)
    pairs = {(d, n) for d, n, _ in here} | {(d, n) for x in notes for d, n in x.get("짝", [])}
    spans = {}
    for c in [cid] + [x["청크"] for x in notes]:
        if c in CHUNK_CUES:
            spans.setdefault(CHUNK_DOC[c], []).append(CHUNK_CUES[c])
    seen = lambda d, n: any(lo <= n <= hi for lo, hi in spans.get(d, [])) or (d, n) in pairs
    out = []
    for d, n in MEMO_REF.findall(memo):
        d, n = re.sub(r"\s*#\d+/\d+$", "", d.strip()), int(n)
        if d in CUES and not seen(d, n):
            out.append(f"«{d}» 큐 {n}은 이 원문(큐 {a}~{b})에도 ↔ 짝 줄에도 없다" if d == doc
                       else f"«{d}» 큐 {n}은 이 원문에 ↔ 짝 줄로 나오지 않았다")
    mates = {n for _, n, _ in here}
    for ln in memo.split("\n"):
        if "«" in ln or "↔" in ln:
            continue
        for n in map(int, MEMO_OWN.findall(ln)):
            if not seen(doc, n) and n not in mates:
                out.append(f"큐 {n}은 이 원문(큐 {a}~{b})에 없다")
    return list(dict.fromkeys(out))


def missed_pairs(memo, cid, t):
    """짝 줄 기록 확인(P): 큐가 적은 짝 트랙(강제 자막 등, SMALL_CUES 이하)의 ↔ 줄은 하나하나가 질문의 재료다.
    메모에 붙은 큐 번호도 짝 큐 번호도 없으면 빠뜨린 것 — q11 SDH 큐 113 '태산'에 강제 자막 큐 1이 붙어 있었는데
    메모가 안 적고 원고는 'SDH에 없다'고 썼다. 번역 트랙 짝은 줄마다 붙으니 검사하지 않는다."""
    miss = []
    for d, n, host in pair_hosts(cid, t):
        if len(CUES[d]) > SMALL_CUES:
            continue
        own = host is not None and re.search(rf"큐\s*{host}(?!\d)", memo)
        theirs = re.search(rf"«{re.escape(d)}»\s*큐\s*{n}(?!\d)", memo)
        if not own and not theirs:
            miss.append((d, n, host))
    return miss


def _drop_bad_lines(memo, cid, t, notes):
    return "\n".join(ln for ln in memo.split("\n") if not memo_issues(ln, cid, t, notes)).strip()


def check_memo(memo, cid, t, prompt, notes=()):
    """M → P 순서로 한 번씩 되묻는다. 되물어도 틀린 줄은 지운다(틀린 번호가 원고로 올라가지 않게).
    줄을 지우고 남은 게 없으면 '관련 없음'으로 둔다(빈 메모가 관련 있는 메모로 세어지지 않게).
    돌려주는 기록: {'틀림': [...], '짝누락': [...], '지운줄': n} 또는 None(문제 없음)"""
    rec = {}
    bad = memo_issues(memo, cid, t, notes)
    if bad:
        with _cost_lock:
            COST["check_ask"] += 1
        fixed = ask(prompt + f"\n\n네가 쓴 메모:\n{memo}\n\n코드가 원문과 대조하니 틀린 번호가 있다:\n"
                    + "\n".join(f"- {x}" for x in bad)
                    + "\n메모 전체를 다시 써라. 큐 번호는 원문의 [큐 N | 시각] 줄과 ↔ 줄에 실제로 있는 것만 써라. 메모만 답하라.", "sub").strip()
        if not irrelevant(fixed):
            memo = fixed
        left = memo.count("\n") + 1
        memo = _drop_bad_lines(memo, cid, t, notes)
        rec.update({"틀림": bad, "지운줄": left - (memo.count("\n") + 1 if memo else 0)})
        if not memo:
            return "관련 없음", rec
    miss = missed_pairs(memo, cid, t)
    if miss:
        with _cost_lock:
            COST["check_ask"] += 1
        spots = "\n".join(f"- [큐 {h}] 줄의 ↔ «{d}» 큐 {n}" if h else f"- 짝 트랙에만 있는 «{d}» 큐 {n}" for d, n, h in miss)
        more = ask(prompt + f"\n\n네가 쓴 메모:\n{memo}\n\n원문의 아래 짝이 메모에 빠졌다. 짝마다 두 큐의 본문이 어떻게 같고 다른지"
                   f"(빠지거나 더해진 것) 한 줄씩 적어라. 원문에 있는 그대로, 큐 번호를 붙여서. 더할 줄만 답하라.\n{spots}", "sub").strip()
        more = _drop_bad_lines(more, cid, t, notes)
        if more and not irrelevant(more):
            memo = memo + "\n" + more
        rec["짝누락"] = [[d, n] for d, n, _ in miss]
    return memo, (rec or None)


PAIR_LIMIT = 12000


def _mates(cid, t):
    doc = CHUNK_DOC[cid]
    ds = [_doc_of(x) for x in t["시작문서"] if _chunks_of(x)] + list(t["기준자료"])
    return [d for d in dict.fromkeys(ds) if d in CUES and d != doc and _same_scene(doc, d)][:2]


def _align(cid, t):
    """맞대기 계산: (이 청크 큐들, {이 트랙 큐 번호: [↔ 줄]}, 짝 없는 ↔ 줄, 붙인 짝 문서).
    ↔ 줄마다 (문서, 짝 큐 번호, 붙은 큐 번호)도 PAIR_HOSTS에 남긴다 — 짝 줄 기록 확인(P)이 쓴다."""
    doc = CHUNK_DOC[cid]
    a, b = CHUNK_CUES[cid]
    rows = [c for c in CUES[doc] if a <= c[0] <= b]
    t0, t1 = CHUNK_TIME[cid]
    attach, orphans, used, hosts = {}, [], [], []
    for d in _mates(cid, t):
        mine = [m for m in CUES[d] if m[1] < t1 and m[4] > t0]
        if sum(len(m[3]) + 30 for m in mine) > PAIR_LIMIT:
            continue
        used.append(d)
        for m in mine:
            best, ov = None, 0.0
            for r in rows:
                o = min(r[4], m[4]) - max(r[1], m[1])
                if o > ov:
                    best, ov = r[0], o
            line = f"    ↔ «{d}» 큐 {m[0]} | {m[2]}: {m[3]}"
            (attach.setdefault(best, []).append(line) if best else orphans.append(line))
            hosts.append((d, m[0], best))
    return rows, attach, orphans, used, hosts


def pair_hosts(cid, t):
    """[(짝 문서, 짝 큐 번호, 붙은 이 트랙 큐 번호 또는 None)]"""
    return _align(cid, t)[4] if cid in CHUNK_TIME else []


def render_aligned(cid, t):
    """맞대기 보기: 트랙 청크를 읽을 때, 이 절이 맡거나 기준으로 받은 같은 회차 다른 트랙(최대 둘)의 큐를
    **시간이 겹치는 줄 바로 아래** 코드가 붙인다. 짝 큐는 가장 많이 겹치는 줄 하나에만 붙인다.
    - 두 트랙을 따로 읽고 모델이 시각을 기억해 맞추게 했더니 틀렸다(q11: SDH 큐 113에 '태산'이 있는데 '빠졌다')
    - 짝 목록을 청크 끝에 통째로 붙여도 틀렸다(긴 목록에서 같은 시각 줄을 못 찾음)
    붙는 분량이 PAIR_LIMIT를 넘는 짝(회차 전체에 걸친 강제 자막 청크의 짝 = SDH 전체 등)은 붙이지 않는다."""
    base = render(cid)
    if cid not in CHUNK_TIME:
        return base
    rows, attach, orphans, used, _ = _align(cid, t)
    if not used:
        return base
    head = CHUNKS[cid].split("\n", 1)[0]
    body = []
    for n, _, st, tx, _ in rows:
        body.append(f"[큐 {n} | {st}] {tx}")
        body += attach.get(n, [])
    note = (f"(↔ 줄 = 같은 시간에 겹치는 {', '.join(f'«{d}»' for d in used)}의 큐. ↔ 줄이 없는 큐는 그 시간에 짝 트랙 큐가 없다는 뜻)")
    tail = ("\n짝 트랙에만 있는 큐(이 청크의 어느 큐와도 시간이 안 겹침):\n" + "\n".join(orphans)) if orphans else ""
    return head + "\n" + note + "\n" + "\n".join(body) + tail


PAIR_LINE = re.compile(r"↔ «([^»]+)» 큐 (\d+) \|")


def pair_seen(cid, t):
    """맞대기 보기로 조사관이 실제로 본 짝 트랙 큐 [(문서, 큐 번호)] — 짝 트랙 인용을 허위로 세지 않게."""
    return [[d, int(n)] for d, n in PAIR_LINE.findall(render_aligned(cid, t))] if cid in CHUNK_TIME else []


def seen_docs(notes):
    """읽은 문서 + 맞대기 보기로 본 짝 문서."""
    return {CHUNK_DOC[n["청크"]] for n in notes} | {d for n in notes for d, _ in n.get("짝", [])}


def pick_next(t, question, notes, cands):
    """후보 중 하나를 모델이 고르고, 코드가 후보 안에 있는지 다시 확인한다(없는 청크 id를 지어내면 첫 후보)."""
    memo = "\n".join(f"- {n['청크']}: {n['메모'][:150]}" for n in notes)
    why = anchors(t, [n["청크"] for n in notes])
    prompt = f"""{_brief(t, question)}

지금까지 읽은 것(메모 앞부분):
{memo}

다음에 읽을 청크를 후보에서 하나 골라라. 규정과 실제 트랙을 맞대는 것이 목적이므로, 규정을 아직 한 청크도 안 읽었으면 관련 규정 청크를 우선 고려하라.
후보:
{chr(10).join(_cand_line(c, why.get(c, "")) for c in cands)}

JSON으로만 답하라: {{"청크": "후보의 id 그대로"}}"""
    pick = _clean(ask(prompt, "sub", as_json=True).get("청크", ""))
    return pick if pick in cands else cands[0]


CITE = re.compile(r"«([^»]+)»")
CUE_AFTER = re.compile(r"^[\s,)(]*큐\s*(\d+)")


def citations(text):
    """원고 속 «제목» 인용과, 바로 뒤에 붙은 '큐 N'을 뽑는다. 청크 id(«제목 #2/7»)로 적어도 문서 제목으로 모은다."""
    out = []
    for m in CITE.finditer(text):
        title = re.sub(r"\s*#\d+/\d+$", "", m.group(1).strip())
        cue = CUE_AFTER.match(text[m.end(): m.end() + 20])
        out.append((title, int(cue.group(1)) if cue else None))
    return out


AN8 = "{\\an8}"


def track_stats(doc):
    """표기 통계(C): 트랙 **전체**의 표기 수를 코드가 센 사실 요약(원문 발췌 아님).
    조사관은 몇 청크만 읽으므로 '효과음 표기가 없다/있다'를 트랙 전체로 말할 수 없었다 —
    q03 등산 SDH는 효과음·음악 [ ]가 0건인데 팀·대조군 모두 놓쳤고, {\\an8}(위치 명령)을 내용으로 읽었다."""
    k = dict.fromkeys(["lead", "only", "mid", "music", "verb", "paren0", "paren", "note", "hash", "caps", "hyphen",
                       "an8", "l16", "l20", "l42"], 0)
    longest = 0
    for c in CUES[doc]:
        k["note"] += "♪" in c[3]
        k["an8"] += AN8 in c[3]
        for ln in c[3].split(" / "):
            s = ln.replace(AN8, "").replace("‪", "").replace("‬", "").strip()
            n = len(s)
            longest = max(longest, n)
            k["l16"] += n > 16
            k["l20"] += n > 20
            k["l42"] += n > 42
            k["hyphen"] += s.startswith("-")
            s = s.lstrip("-– ").strip()
            k["paren0"] += s.startswith("(")
            k["paren"] += "(" in s
            k["hash"] += "#" in s
            k["caps"] += bool(re.match(r"[A-Z][A-Z .'\-]{1,20}:", s))
            tags = re.findall(r"\[([^\]]+)\]", s)
            if not tags:
                continue
            k["music"] += sum("음악" in x or "music" in x.lower() for x in tags)
            k["verb"] += sum(x.strip().endswith("다") for x in tags)
            if re.fullmatch(r"(\[[^\]]+\]\s*)+", s):
                k["only"] += 1
            elif s.startswith("["):
                k["lead"] += 1
            else:
                k["mid"] += 1
    # 'N큐'처럼 숫자와 '큐'를 붙여 쓰면 모델이 '큐 N'(큐 번호)으로 옮겨 적었다(예시 코퍼스 대조군) — 개수는 'N개'로
    return "\n".join([
        f"«{doc}»: 큐 총 {len(CUES[doc])}개",
        f"  - [ ]: 줄 머리 [ ] 뒤에 같은 줄 대사가 이어짐 {k['lead']}줄(화자 표기로 보임) · [ ]만 있는 줄 {k['only']}줄"
        f"(효과음·음악, 또는 다음 줄 대사의 화자) · 줄 중간 [ ] {k['mid']}줄",
        f"  - [ ] 안에 '음악'·music {k['music']}개 · [ ] 안이 '-다'로 끝남(서술형) {k['verb']}개",
        f"  - 소괄호: 소괄호로 시작하는 줄 {k['paren0']}줄 · 소괄호가 든 줄 {k['paren']}줄",
        f"  - ♪가 든 큐 {k['note']}개 · #이 든 줄 {k['hash']}줄",
        f"  - 대문자 화자명(NAME:)으로 시작하는 줄 {k['caps']}줄 · 하이픈(-)으로 시작하는 줄 {k['hyphen']}줄",
        f"  - 줄 길이: 가장 긴 줄 {longest}자 · 16자 넘는 줄 {k['l16']}줄 · 20자 넘는 줄 {k['l20']}줄 · 42자 넘는 줄 {k['l42']}줄",
        f"  - {AN8}가 든 큐 {k['an8']}개 ({AN8}는 화면 위쪽에 띄우는 위치 명령이지 내용이 아니다)"])


def stats_block(docs):
    tracks = [d for d in docs if d in CUES]
    if not tracks:
        return ""
    return ("트랙 표기 통계 — 코드가 트랙 **전체**(읽지 않은 구간 포함)를 센 개수. 큐 번호가 아니다.\n"
            "표기가 있다·없다·몇 번이라고 쓸 때는 이 수를 먼저 보라. 규정과 다른 표기가 몇 개라도 있으면 '모두 규정에 맞다'고 쓰지 마라.\n"
            + "\n".join(track_stats(d) for d in tracks) + "\n\n")


def _pool(notes):
    """인용문을 찾아볼 원문 = 읽은 청크 + 맞대기 보기로 본 짝 큐 본문(공백·문장부호 무시)."""
    import metrics
    cue_text = {(d, c[0]): c[3] for d in {d for n in notes for d, _ in n.get("짝", [])} for c in CUES[d]}
    parts = [CHUNKS[n["청크"]] for n in notes] + [cue_text.get((d, k), "") for n in notes for d, k in n.get("짝", [])]
    text = "\n".join(parts)
    return metrics._norm(text) + "\n" + metrics._norm(metrics.TAGS.sub("", text))


def check_quotes(t, question, draft, notes):
    """집필 인용문 대조(B·B+): 틀린 인용 문장만 골라 한 번 다시 쓰게 하고, 고친 문장도 틀리면 지운다.
    돌려주는 것: (원고, {'틀림': n, '고침': n, '지움': n, '사례': [...]})"""
    import metrics
    tracks = {CHUNK_DOC[n["청크"]] for n in notes if n["청크"] in CHUNK_TIME}
    pool = _pool(notes)
    spans = [(CHUNK_DOC[n["청크"]], CHUNK_CUES[n["청크"]]) for n in notes if n["청크"] in CHUNK_CUES]
    pairs = {(d, k) for n in notes for d, k in n.get("짝", [])}
    seen_cue = lambda d, k: (d, k) in pairs or any(d == x and a <= k <= b for x, (a, b) in spans)
    mod = sys.modules[__name__]
    issues = metrics.quote_issues(draft, tracks, pool, mod, seen_cue)
    rec = {"틀림": len(issues), "고침": 0, "지움": 0, "사례": [[s[:200], k] for s, k, _ in issues][:10]}
    if not issues:
        return draft, rec
    # 번호를 키로 받는다 — 목록으로 받으면 모델이 하나를 빼먹었을 때 뒤 문장의 수정문이 앞 문장 자리에 들어간다
    keys = [str(i) for i in range(1, len(issues) + 1)]
    shape = "{" + ", ".join(f'"{k}": "{k}번 고친 문장"' for k in keys) + "}"
    with _cost_lock:
        COST["check_ask"] += 1
    lines = "\n".join(f"{i}. 문장: {s}\n   문제: {why}" for i, (s, _, why) in enumerate(issues, 1))
    out = ask(f"""{_brief(t, question)}

네가 쓴 원고에서 아래 문장의 인용문이 원문과 맞지 않는다고 코드가 확인했다.
{lines}

문장마다 고친 문장 하나를 써라.
- '실제 본문'이 주어졌으면 인용문과 설명을 그 본문에 맞게 고쳐라. 본문에 없는 내용을 지어내지 마라.
- 원문에 없는 인용문이면 따옴표 인용을 빼고 메모에 있는 사실만 남겨라. 남길 것이 없으면 빈 문자열("")을 써서 그 문장을 지운다.
- «자료 제목»과 '큐 N' 표기는 원래 문장처럼 유지하라.

JSON으로만 답하라. 키는 위 문장 번호다: {shape}""", "sub", as_json=True)
    if not isinstance(out, dict) or not any(k in out for k in keys):
        rec["고침없음"] = True        # 답을 못 받았다(JSON 실패 등) — 멀쩡한 문장까지 지우지 않게 원고를 그대로 둔다
        return draft, rec
    for k, (sent, _, _) in zip(keys, issues):
        rep = str(out.get(k) or "").strip()
        if rep and not metrics.quote_issues(rep, tracks, pool, mod, seen_cue):
            draft = draft.replace(sent, rep, 1)
            rec["고침"] += 1
        else:
            draft = draft.replace(sent, "", 1)
            rec["지움"] += 1
    # 지운 자리에 남은 겹공백만 정리한다(줄 머리 들여쓰기는 그대로)
    return "\n".join(re.sub(r"(?<=\S)[ \t]{2,}", " ", ln).rstrip() for ln in draft.split("\n")).strip(), rec


def cite_rules(got):
    """인용 규칙 — 팀 조사관(write_section)과 대조군(baseline.write_report)이 **같은 문자열**을 쓴다.
    문구가 다르면 두 쪽의 인용 차이가 '분업이 없어서'인지 '지시가 달라서'인지 가를 수 없다.
    (대조군만 남의 예시 «아파트 E09 한국어 SDH» 큐 212와 '(작품 이름 등)'이 빠진 문구를 받고 있었다)"""
    # 예시 문장에 실제로 읽은 트랙 제목을 넣는다 — 남의 예시(아파트 E09)만 주었더니 번역 절들이 «»를 아예 안 썼다(q10)
    tr = next((CHUNK_DOC[n["청크"]] for n in got if n["청크"] in CHUNK_TIME), None)
    example = (f'"…라고 옮겼다(«{tr}» 큐 {CHUNK_CUES[next(n["청크"] for n in got if n["청크"] in CHUNK_TIME)][0]})."'
               if tr else '"…를 요구한다(«규정 제목» I.8)."')
    return f"""- 사실을 적는 문장마다 근거 자료를 아래 '인용할 수 있는 자료' 목록의 제목 그대로 «» 안에 적어라. 목록 밖의 이름(작품 이름 등)에는 «»를 쓰지 마라.
- 트랙 근거는 «제목» 바로 뒤에 '큐 N'을 붙여라. 큐 번호는 그 트랙의 번호여야 한다(짝 트랙 큐를 섞지 마라).
  예: {example}
- 인용(«»)이 하나도 없는 원고는 근거 없는 글로 판정된다(평가 지표 무근거절).
"""


def write_section(t, question, notes):
    got = [n for n in notes if not irrelevant(n["메모"])]
    if not got:
        # 메모가 전부 '관련 없음'인데 원고를 쓰게 하면 모델이 상식으로 지어냈다(q10 영어 번역: 읽은 6청크 전부 관련 없음 → 번역문까지 지어낸 534자)
        return {"원고": "", "충분": False, "부족": "읽은 청크에서 재료를 하나도 찾지 못했다. 다른 구간을 읽어야 한다."}
    memo = "\n\n".join(f"[자료 «{CHUNK_DOC[n['청크']]}» · 청크 {n['청크'].rsplit('#', 1)[-1]}]\n{n['메모']}"
                         for n in got) or "(관련 메모 없음)"
    titles = "\n".join(f"«{d}»" for d in dict.fromkeys(CHUNK_DOC[n["청크"]] for n in got))
    read = {n["청크"] for n in notes}
    mine = [c for d in t["시작문서"] for c in _chunks_of(d)]
    # 규정만 묻는 절(q01·q02)에 '트랙 사례와 맞대라'를 시키면 없는 트랙을 이유로 부족 신고를 한다(q01 실측)
    pair = ("- 규정 조항과 실제 트랙 사례를 맞대어 맞는지·어긋나는지를 적어라.\n" if any(_is_track(d) for d in t["시작문서"] if _chunks_of(d))
            else "- 규정 조항의 번호와 요구 내용을 정확히 옮겨라. 트랙 사례는 이 절의 몫이 아니다.\n")
    cover = (f"맡은 자료 청크 {len(mine)}개 중 {sum(c in read for c in mine)}개를 읽었고, "
             f"읽은 {len(notes)}청크 중 {len(notes) - len(got)}개는 관련 없음이었다.")
    prompt = f"""{_brief(t, question)}
읽은 범위: {cover}

아래 메모만 근거로 보고서의 이 절 원고를 써라.
- 8~15문장, 700자 이상. 메모에 없는 사실은 쓰지 마라.
{cite_rules(got)}{pair}- 읽지 않은 구간에 대해서는 '없다'고 단정하지 마라. 메모에 없는 것은 '확인하지 못했다'고 적어라.
- 마지막으로 스스로 판단하라: 이 절이 지시에 답하기에 충분한가? 부족하면 무엇이 비었는지(어떤 자료·구간·조항을 더 봐야 하는지) 한 문장으로.

인용할 수 있는 자료:
{titles or "(없음)"}

{stats_block(sorted(seen_docs(got)))}메모:
{memo}

JSON으로만 답하라: {{"원고": "...", "충분": true 또는 false, "부족": "부족하면 무엇이 비었는지, 충분하면 빈 문자열"}}"""
    return ask(prompt, "sub", as_json=True)


def irrelevant(memo):
    """'관련 없음' 판정. 모델이 '관련 없음.'처럼 마침표를 붙여 내기도 한다."""
    return re.sub(r"[\s.。!]", "", memo) == "관련없음"


def _progress(event):
    """조사관이 청크 하나를 읽을 때마다 LangGraph 사용자 정의 스트림으로 알린다(데모의 진행 표시).
    stream_mode에 'custom'이 없으면(invoke·절제 실험) 아무것도 안 한다. 청크 id·제목만 보내고 원문은 안 보낸다."""
    try:
        from langgraph.config import get_stream_writer
        get_stream_writer()(event)
    except Exception:          # 그래프 밖에서 부른 경우 등 — 진행 표시는 결과에 영향이 없어야 한다
        pass


def researcher(s):
    """노드 안의 작은 에이전트: 예산만큼 청크를 읽고(첫 청크는 배정대로, 이후는 모델이 후보에서 고름) 절 원고를 쓴다.
    재위임이면 지난 메모·읽은 청크에서 이어 읽는다(처음부터 다시 안 읽음). 예산은 바퀴마다 새로 받는다."""
    t, prior, q = s["task"], s.get("prior") or {}, s["question"]
    read = list(prior.get("읽은청크", []))
    notes = list(prior.get("메모", []))
    new = []
    # 예산 두 가지: 기준 예산(규정 청크만) + 맡은 자료 예산. 순서 = 첫 시작 청크 → 규정 → 나머지.
    # - 기준 예산을 따로 둔 이유: 한 예산이면 조사관이 트랙만 읽고 규정을 한 줄도 안 본 채 '규정과 맞다'고 썼다(q11 첫 실측 규정대조율 0%)
    # - 규정을 앞에 두는 이유: 뒤에 두었더니 트랙을 읽는 동안 잣대가 없어 'SDH에 있고 강제 자막에 없는 것'을 모두 위반으로 적었다
    # 재위임 바퀴에는 기준 예산이 없다(규정은 1바퀴에 읽었고, 빈 칸은 대개 자료 쪽이다).
    rule_budget = 0 if prior else t.get("기준예산", 0)
    # 핵심 규정 먼저(A): 맡은 트랙 종류별 필수 규정(required_rules) 중 아직 한 청크도 안 읽은 문서의 청크만 후보로 준다.
    # 모델에게 규정 후보 전부를 주었더니 q11이 가이드 I절만 두 번 고르고 «넷플릭스 강제 자막 이해하기»를 안 읽었다
    must = list(dict.fromkeys(r for d in t["시작문서"] if _chunks_of(d) and _is_track(d)
                              for r in required_rules(_doc_of(d))))
    for step in range(t["예산"] + rule_budget):
        seeds = [c for d in t["시작문서"] for c in _chunks_of(d) if c not in read]
        rule_phase = 1 <= step <= rule_budget
        if step == 0 and seeds and not read:
            cid = seeds[0]
        else:
            cands = frontier(t, read, t["피하기"], rules_only=rule_phase)
            if rule_phase:
                done = {CHUNK_DOC[c] for c in read}
                first = [c for r in must if r not in done for c in DOC_CHUNKS[r]]
                first = [c for c in first if c not in set(t["피하기"])] or first   # 남의 구역은 피한다(다 피해지면 무시)
                cands = first[:25] or cands
            if not cands:
                break
            cid = pick_next(t, q, notes, cands)
        memo, chk = _read_one(cid, t, q, notes)
        notes.append({"청크": cid, "메모": memo, "짝": pair_seen(cid, t), **({"대조": chk} if chk else {})})
        read.append(cid)
        new.append(cid)
        _progress({"절": t["절"], "바퀴": t["바퀴"], "읽음": len(new), "예산": t["예산"] + rule_budget, "청크": cid,
                   "관련없음": irrelevant(memo), "되물음": bool(chk)})
    out = write_section(t, q, notes)
    draft = str(out.get("원고", ""))
    qfix = None
    if 설정["스위치"]["인용대조"] and draft:
        before = len(citations(draft))
        draft, qfix = check_quotes(t, q, draft, notes)
        # 인용 문장을 많이 지웠으면 모델이 먼저 낸 '충분'을 믿지 않는다 → 재위임 대상
        if qfix["지움"] and (qfix["지움"] >= 3 or qfix["지움"] * 10 >= before * 3):
            out = {**out, "충분": False,
                   "부족": f"인용이 원문과 맞지 않는 문장 {qfix['지움']}개를 지웠다. 그 사례의 큐를 다시 읽고 원문대로 적어야 한다."}
    cites = citations(draft)
    read_docs = seen_docs(notes)
    sec = {"절": t["절"], "번호": t["번호"], "바퀴": t["바퀴"],
           "원고": draft, "읽은청크": read, "새로읽은": new, "메모": notes,
           "인용": cites, "허위인용": sorted({c for c, _ in cites if c not in read_docs}),
           # 빈 원고·문자열 "false"를 충분으로 세지 않는다(빈 원고가 재위임에서 빠졌다)
           "충분": out.get("충분") is True and bool(draft), "부족": str(out.get("부족", "")) or "원고가 비었다", "지시": t["지시"],
           **({"인용대조": qfix} if qfix else {})}
    useless = sum(1 for n in notes[-len(new):] if irrelevant(n["메모"])) if new else 0
    fixed = sum(1 for n in notes[-len(new):] if n.get("대조")) if new else 0
    line = (f"   ③ 조사관   «{t['절']}» {len(new)}청크 새로 읽음(관련 없음 {useless}"
            + (f" · 메모 되물음 {fixed}" if fixed else "") + f") → {len(draft)}자 · 인용 {len(cites)}"
            + (f" · 인용 틀림 {qfix['틀림']}(고침 {qfix['고침']} · 지움 {qfix['지움']})" if qfix and qfix["틀림"] else "")
            + ("" if sec["충분"] else f" · 부족 신고: {sec['부족'][:60]}"))
    return {"sections": [sec], "visited": [(t["번호"], c, t["바퀴"]) for c in new], "log": [line]}


# ---------------------------------------------------------------- ④ 점검
def _valid_cites(sec):
    return sum(1 for c, _ in sec["인용"] if c in DOCS and c not in sec["허위인용"])


def review(s):
    """LLM 호출 없음 — 조사관 자기신고를 모아 빈 칸만 다시 보낸다.
    두 번째 원고 채택 규칙: 새 원고의 유효 인용 수가 지난 원고보다 적으면 지난 원고를 지킨다.
    (무조건 덮어쓰면 인용이 빠진 재작성본이 멀쩡한 원고를 지운다. 새로 읽은 메모는 재작성에 다 들어갔으므로
     인용이 줄었다면 글이 나빠진 것이다.) 되돌린 절은 `되돌림`에 남긴다."""
    p = s["plan"]
    adopted = _latest(p.get("채택", {}))
    kept_old = list(p.get("되돌림", []))
    for sec in s["sections"]:
        if sec["바퀴"] != p["바퀴"]:
            continue                                   # 지난 바퀴 원고(리듀서에 쌓여 있음)는 이미 처리함
        old = adopted.get(sec["번호"])
        if old and (not sec["원고"] or _valid_cites(sec) < _valid_cites(old)):
            kept_old.append(sec["절"])
            # 원고는 지키되 이번 바퀴에 읽은 것(청크·메모)은 넘겨받는다 — 다음 바퀴가 같은 청크를 또 읽지 않게
            adopted[sec["번호"]] = {**old, "읽은청크": sec["읽은청크"], "메모": sec["메모"]}
            continue
        adopted[sec["번호"]] = sec
    # 빈 칸 = 이번 바퀴에 보낸 절 중 채택본이 부족한 절(지난 원고를 지킨 절도 포함)
    want = [i for i in p["배치"] if i in adopted and not adopted[i]["충분"]]
    gaps = want
    if not 설정["스위치"]["재위임"]:
        reason, gaps = "재위임 꺼짐", []
    elif p["바퀴"] >= 설정["최대바퀴"]:
        reason, gaps = ("바퀴 소진" if want else "빈 칸 없음"), []
    else:
        reason = "" if gaps else "빈 칸 없음"
    toc = [dict(t) for t in p["목차"]]
    for i in gaps:
        sec = adopted[i]
        seen = ", ".join(f"«{d}»" for d in dict.fromkeys(CHUNK_DOC[c] for c in sec["읽은청크"]))
        toc[i]["지시"] = (f"{p['목차'][i]['지시']} (재위임: 지난번에 {seen}를 읽었지만 {sec['부족']} "
                         f"그 빈 칸을 겨냥해 아직 안 본 청크를 찾아라)")
    line = (f"④ 점검   {len(adopted)}절 중 부족 신고 {sum(not x['충분'] for x in adopted.values())}개 → "
            + (f"{len(gaps)}절 재위임" if gaps else f"종료({reason})")
            + (f" · 지난 원고 지킴: {', '.join(kept_old)}" if kept_old and kept_old != p.get("되돌림", []) else ""))
    return {"plan": {**p, "목차": toc, "채택": {str(k): v for k, v in adopted.items()}, "되돌림": kept_old,
                     "재위임기록": p.get("재위임기록", []) + [toc[i]["절"] for i in gaps],
                     "배치": gaps, "바퀴": p["바퀴"] + (1 if gaps else 0), "종료": reason},
            "log": [line]}


def route(s):
    return "dispatch" if s["plan"]["배치"] else "synthesize"


# ---------------------------------------------------------------- ⑤ 종합
def synthesize(s):
    """절 원고는 고치지 않고 이어 붙인다. 코디네이터는 원고(압축 결과)만 보고 제목·머리말·맺음말을 쓴다 — 원문은 못 본다."""
    p = s["plan"]
    adopted = [v for _, v in sorted(_latest(p["채택"]).items())]
    empty = "_(조사관이 읽은 청크에서 재료를 찾지 못했다)_"
    body = "\n\n".join(f"## {sec['절']}\n\n{sec['원고'] or empty}" for sec in adopted)
    titles = "\n".join(f"«{d}»" for d in sorted(set().union(*[seen_docs(sec["메모"]) for sec in adopted]))) or "(없음)"
    prompt = f"""너는 보고서 편집자다. 아래는 조사관들이 절마다 쓴 원고다. 원고는 고치지 않는다.
질문: {s['question']}

- 제목 한 줄
- 머리말 3~4문장: 질문과 보고서가 어떻게 나뉘었는지
- 맺음말 5~8문장: 절들을 가로질러 질문에 대한 답을 정리하라. 절 원고에 없는 사실은 쓰지 마라. 근거는 원고에 있던 «자료 제목» 그대로 옮겨 적어라.
- «»는 아래 '인용할 수 있는 자료'의 제목에만 쓴다. 작품 이름에는 «»를 붙이지 마라.

인용할 수 있는 자료:
{titles}

{body}

JSON으로만 답하라: {{"제목": "...", "머리말": "...", "맺음말": "..."}}"""
    ed = ask(prompt, "coord", as_json=True)
    who = "\n".join(
        f"- **{sec['절']}** ({sec['바퀴']}바퀴): 읽음 "
        + ", ".join(f"`{c}`" for c in sec["읽은청크"])
        for sec in adopted)
    closing = f"{ed.get('머리말', '')}\n{ed.get('맺음말', '')}"
    all_seen = set().union(*[seen_docs(sec["메모"]) for sec in adopted]) if adopted else set()
    # 코디네이터가 쓴 머리말·맺음말의 인용도 검사한다(대조군은 보고서 전체를 검사하므로 같은 범위로 맞춤)
    closing_false = sorted({c for c, _ in citations(closing) if c not in all_seen})
    report = (f"# {ed.get('제목', s['question'])}\n\n> 질문: {s['question']}\n\n{ed.get('머리말', '')}\n\n{body}\n\n"
              f"## 맺음말\n\n{ed.get('맺음말', '')}\n\n## 부록: 절마다 누가 무엇을 읽었나\n\n{who}\n")
    return {"report": report, "plan": {**p, "맺음말허위인용": closing_false},
            "log": [f"⑤ 종합   {len(adopted)}절 → 보고서 {len(report):,}자"
                    + (f" · 맺음말 허위인용 {len(closing_false)}" if closing_false else "")]}


# ---------------------------------------------------------------- ⑥ 평가
def evaluate(s):
    import metrics
    m = metrics.compute(s, COST, sys.modules[__name__])
    return {"metrics": m, "log": ["⑥ 평가   " + metrics.summary(m)]}


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


def _append_locked(path, line):
    """여러 프로세스(ablation.py)가 동시에 한 파일에 덧붙인다 — 잠금 파일로 차례를 지킨다."""
    import time
    lock = str(path) + ".lock"
    for _ in range(600):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL)
            break
        except FileExistsError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"잠금 파일이 30초 넘게 남아 있다: {lock}")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    finally:
        os.close(fd)
        os.remove(lock)


def slim(row):
    """runs.jsonl에 올리는 한 줄 — 메모(자막 원문 발췌)는 빼고 길이만 남긴다."""
    def lite(x):   # 지워진 인용 문장(자막 발췌가 섞임)은 로컬 runs/에만 — 올리는 쪽엔 종류만
        return {**x, "인용대조": {**x["인용대조"], "사례": [k for _, k in x["인용대조"].get("사례", [])]}} if x.get("인용대조") else x
    return {**row, "sections": [{**lite(x), "메모": [{"청크": n["청크"], "메모글자": len(n["메모"]), "관련없음": irrelevant(n["메모"]),
                                              **({"대조": n["대조"]} if n.get("대조") else {})}
                                             for n in x["메모"]]} for x in row["sections"]]}


def save(out, qid, tag):
    """저장 두 벌.
    - output/runs.jsonl 한 줄 + output/reports/*.md: 저장소에 올리는 것. 메모(자막 원문 발췌가 많음)는 빼고 길이만 남긴다
    - output/runs/*.json: 메모까지 전부. 로컬 전용(gitignore) — 데모 화면에서 '무엇을 읽었나'를 펼쳐 볼 때 쓴다"""
    import datetime
    od = OUT
    for sub in ("reports", "runs"):
        (od / sub).mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{qid}_{tag}_{stamp}_{os.getpid() % 10000:04d}"
    import metrics   # 보고서 파일에는 작품 제목에서 트랙 종류를 뗀 표기로(인용 검사·지표는 이미 끝남)
    (od / "reports" / f"{name}.md").write_text(metrics.display_titles(out["report"], metrics.track_labels(META)),
                                              encoding="utf-8")
    secs = [v for _, v in sorted(_latest(out["plan"]["채택"]).items())]
    row = {"run": name, "qid": qid, "tag": tag, "question": out["question"], "config": 설정,
           "plan": {k: v for k, v in out["plan"].items() if not k.startswith("_") and k != "채택"},
           "sections": secs, "visited": out.get("visited", []), "metrics": out["metrics"], "log": out.get("log", []),
           "report_file": f"reports/{name}.md"}
    (od / "runs" / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _append_locked(od / "runs.jsonl", json.dumps(slim(row), ensure_ascii=False))
    except RuntimeError as e:      # 잠금이 안 풀려도 실행 결과(runs/*.json)는 이미 저장됨 — 실행을 잃지 않는다
        print(f"경고: runs.jsonl 덧붙이기 실패({e}). {out_dir()}/runs/{name}.json은 저장됨")
    return name


def out_dir():
    """저장 폴더를 저장소 기준 경로로 — '저장: output/reports/…'(ablation.py가 이 줄을 읽음)"""
    return OUT.relative_to(ROOT).as_posix()


def run(question, qid="custom", tag="기본", quiet=False, keep=True, on_step=None):
    """on_step(노드 이름, 그 노드가 남긴 로그 줄들) — 주면 LangGraph 스트리밍으로 노드가 끝날 때마다 부른다(데모의 진행 표시).
    병렬 조사관은 한 명이 끝날 때마다 따로 온다. 조사관이 청크를 하나 읽을 때마다는 on_step("읽기", [사건 dict])로 온다(custom 스트림).
    결과는 invoke와 같다(마지막 'values'가 최종 State)."""
    for k in COST:
        COST[k] = 0
    app, cfg = build(), {"recursion_limit": 80}
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
    if not quiet:
        for line in out["log"]:
            print(line)
    if keep:
        out["run"] = save(out, qid, tag)
    return out


def apply_off(names):
    """--off 배정검사,남의구역 → 스위치를 끈다. 없는 이름이면 멈춘다(로그만 찍고 경로는 그대로인 사고 방지)."""
    for n in names:
        if n not in 설정["스위치"]:
            raise SystemExit(f"없는 스위치: {n} (있는 것: {', '.join(설정['스위치'])})")
        설정["스위치"][n] = False


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("q", nargs="?", default="s02" if SAMPLE else "q03", help="질문 id(q01~q12, 예시 모드는 s01~s03) 또는 질문 원문")
    ap.add_argument("--sample", action="store_true", help="예시 코퍼스로(모듈을 불러올 때 이미 반영됨)")
    ap.add_argument("--off", default="", help="끌 스위치, 쉼표로: 배정검사,남의구역,재위임,인용대조")
    ap.add_argument("--tag", default="", help="저장 이름표(기본: 끈 스위치로 만듦)")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    offs = [x for x in a.off.split(",") if x]
    apply_off(offs)
    qid = a.q if a.q in QUESTIONS else "custom"
    q = QUESTIONS[a.q]["question"] if a.q in QUESTIONS else a.q
    n_chars = sum(len(v) for v in DOCS.values())
    print(f"코퍼스 {len(DOCS)}건 · {n_chars:,}자 · 청크 {len(CHUNKS)}개 (청크당 {설정['청크글자']:,}자 이하)")
    print(f"스위치: {설정['스위치']}\n\n질문: {q}\n")
    out = run(q, qid, a.tag or ("기본" if not offs else "off-" + "-".join(offs)), keep=not a.no_save)
    if out.get("run"):
        print(f"\n저장: {out_dir()}/reports/{out['run']}.md")
