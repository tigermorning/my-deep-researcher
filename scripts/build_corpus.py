# -*- coding: utf-8 -*-
"""data/sources.json 목록대로 로컬 원본을 읽어 data/corpus.json(docs + links)을 만든다.

    python scripts/build_corpus.py

- 넷플릭스 규정: subtitle-help-agent가 받아 둔 마크다운
- 작업자 자료: 디즈니+·쿠팡플레이 실무 규정(구글독스 텍스트 추출본)
- 자막 트랙: srt 파일, 또는 mkv 내장 트랙을 ffmpeg로 뽑은 것(data/raw/tracks/에 캐시)

본문은 저작물이므로 corpus.json과 data/raw/는 .gitignore로 막는다.
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "raw" / "tracks"


def expand(p):
    return Path(p).expanduser()


def load_srt(text):
    """srt를 큐 한 줄씩으로 줄인다: `번호<TAB>시작 --> 끝<TAB>1행 / 2행`."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        cues.append(f"{lines[0].strip()}\t{lines[1].strip()}\t{' / '.join(lines[2:])}")
    return cues


def extract_stream(ffmpeg, mkv, stream):
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{Path(mkv).stem}.s{stream}.srt"
    if not out.exists():
        subprocess.run([str(ffmpeg), "-v", "error", "-y", "-i", str(mkv), "-map", f"0:{stream}", str(out)],
                       check=True)
    return out.read_text(encoding="utf-8")


LANG = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh-Hans": "중국어 간체", "zh-Hant": "중국어 번체"}
KIND = {"sdh": "SDH·CC(같은 언어)", "translation": "번역 자막", "forced": "강제 자막",
        "subtitle": "같은 언어 자막(SDH 아님)"}


def split_guide(md, marks):
    """가이드를 절 단위로 자른다. 첫 표시 앞 머리말은 내용 절(종류가 있는 것)마다 앞에 붙인다."""
    lines = md.split("\n")
    starts = []
    for title, pat, kind in marks:
        hit = [i for i, l in enumerate(lines) if re.search(pat, l)]
        if len(hit) != 1:
            raise SystemExit(f"절 표시가 {len(hit)}번 잡힘: {title} ({pat})")
        starts.append(hit[0])
    if starts != sorted(starts):
        raise SystemExit(f"절 순서가 어긋남: {marks}")
    head = "\n".join(lines[:starts[0]])
    out = []
    for n, (mark, s) in enumerate(zip(marks, starts)):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[s:e])
        out.append((mark, (head + "\n" + body) if mark[2] else body))
    return out


def track_title(t):
    ep = f" {t['ep']}" if t["ep"] else ""
    return f"{t['work']}{ep} {t['track']}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    src = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
    roots = {k: expand(v) for k, v in src["roots"].items()}

    docs, meta = {}, {}
    links = defaultdict(set)

    def link(a, b):
        if a != b:
            links[a].add(b)
            links[b].add(a)

    # 넷플릭스 규정 — 언어별 가이드 중 splits에 있는 것은 절 단위 문서로 나눈다
    nf_docs, nf_refs = {}, {}          # 글 번호 → 문서 제목 목록, 글 번호 → 본문이 가리키는 글 번호
    guide = {}                         # (언어, 종류) → 문서 제목. 종류 None = 나누지 않은 가이드 전체
    for aid, title, lang in src["netflix"]:
        body = (roots["netflix"] / f"netflix-{aid}.md").read_text(encoding="utf-8")
        base = {"type": "rule", "platform": "넷플릭스", "lang": lang, "source_id": aid,
                "url": f"https://partnerhelp.netflixstudios.com/hc/en-us/articles/{aid}"}
        if aid in src["splits"]:
            parts = split_guide(body, src["splits"][aid])
            for (ptitle, _pat, kind), text in parts:
                docs[ptitle] = text
                meta[ptitle] = {**base, "section": kind}
                if kind:
                    guide[(lang, kind)] = ptitle
            nf_docs[aid] = [p[0][0] for p in parts]
        else:
            docs[title] = body
            meta[title] = base
            nf_docs[aid] = [title]
            if lang:
                guide[(lang, None)] = title
        # 마크다운 변환에서 링크가 빠지므로 참조는 원본 HTML에서 뽑는다
        html = json.loads((roots["netflix"] / f"netflix-{aid}.json").read_text(encoding="utf-8"))["article"]["body"]
        nf_refs[aid] = set(re.findall(r"articles/(\d+)", html))

    # 작업자 자료
    for fname, title in src["worker"]:
        docs[title] = (roots["worker"] / fname).read_text(encoding="utf-8")
        meta[title] = {"type": "rule", "platform": "넷플릭스·디즈니+·쿠팡플레이 실무", "lang": "ko",
                       "source_id": fname}

    # 자막 트랙 — 첫 줄에 원어·자막 언어·종류를 밝혀, 읽는 쪽이 어느 규정을 댈지 알게 한다
    for t in src["tracks"]:
        if "srt" in t:
            raw = (roots["subs"] / t["srt"]).read_text(encoding="utf-8")
        else:
            raw = extract_stream(roots["ffmpeg"], roots["mkv"] / t["mkv"], t["stream"])
        cues = load_srt(raw)
        if not cues:
            raise SystemExit(f"큐 0개: {track_title(t)} — 원본 경로나 형식을 확인")
        title = track_title(t)
        header = (f"[작품 원어: {LANG[t['orig_lang']]} | 자막 언어: {LANG[t['lang']]} | "
                  f"종류: {KIND[t['kind']]} | 플랫폼: {t['platform']}]")
        docs[title] = header + "\n" + "\n".join(cues)
        meta[title] = {"type": "track",
                       **{k: t[k] for k in ("work", "platform", "ep", "track", "orig_lang", "lang", "kind")},
                       "cues": len(cues)}

    # --- links (코드가 규칙으로 만든다) ---
    rules_general = nf_docs["215758617"][0]
    forced_rules = nf_docs["217558918"] + nf_docs["224198488"]
    w_basic, w_spelling, w_sfx = "작업자 자료: 작업 기본 원칙", "작업자 자료: 표기·맞춤법·번역", "작업자 자료: SDH 효과음 예시"

    # 1) 규정 글이 본문에서 가리키는 다른 규정 글 (나뉜 가이드는 모든 절과 잇는다)
    for aid, refs in nf_refs.items():
        for ref in refs & nf_docs.keys():
            for a in nf_docs[aid]:
                for b in nf_docs[ref]:
                    link(a, b)
    # 2) 같은 가이드의 절끼리, 언어별 가이드 ↔ 일반 요구사항, 작업자 자료 ↔ 넷플릭스 한국어 가이드
    for aid in (k for k in src["splits"] if not k.startswith("_")):
        for a in nf_docs[aid]:
            for b in nf_docs[aid]:
                link(a, b)
    for g in guide.values():
        link(g, rules_general)
    link(w_basic, guide[("ko", "translation")])
    link(w_basic, guide[("ko", "sdh")])
    link(w_sfx, guide[("ko", "sdh")])
    link(w_basic, w_sfx)
    link(w_basic, w_spelling)
    # 3) 본문에 링크가 없는 짧은 글은 sources.json의 extra_links(이유 포함)로 잇는다
    by_source = defaultdict(list)
    for k, m in meta.items():
        if m["type"] == "rule":
            by_source[m["source_id"]].append(k)
    for x, y, _why in src["extra_links"]:
        for a in by_source[x]:
            for b in by_source[y]:
                link(a, b)

    tracks = [k for k, m in meta.items() if m["type"] == "track"]
    for a in tracks:
        ma = meta[a]
        # 4) 같은 작품의 다른 트랙·회차
        for b in tracks:
            if meta[b]["work"] == ma["work"]:
                link(a, b)
        # 5) 트랙 → 그 플랫폼·언어·종류에 맞는 규정
        if ma["platform"] == "넷플릭스":
            section = "sdh" if ma["kind"] == "sdh" else "translation"
            g = guide.get((ma["lang"], section)) or guide.get((ma["lang"], None))
            # 원어와 같은 언어의 비SDH 자막(영어 원작의 영어 자막)은 맞는 절이 없다 → 일반 요구사항만
            if ma["kind"] == "subtitle" or g is None:
                g = rules_general
            link(a, g)
        else:
            link(a, w_basic)
            if ma["lang"] == "ko" and ma["kind"] == "translation":
                link(a, w_spelling)
        if ma["lang"] == "ko" and ma["kind"] == "sdh":
            link(a, w_sfx)
        if ma["kind"] == "forced":
            for r in forced_rules:
                link(a, r)

    corpus = {
        "_설명": "자막 규정(넷플릭스 파트너헬프 + 작업자 실무 자료)과 플랫폼별 실제 자막 트랙. 로컬 전용 — 저장소에 올리지 않음",
        "_수집일": date.today().isoformat(),
        "_트랙형식": "큐 한 줄 = 번호<TAB>시작 --> 끝<TAB>1행 / 2행",
        "meta": meta,
        "docs": docs,
        "links": {k: sorted(v) for k, v in sorted(links.items())},
    }
    for k in list(links):
        assert k in docs, k
    (DATA / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- 통계 ---
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")  # gpt-4o / gpt-4o-mini
    rows, tot_c, tot_t = [], 0, 0
    for k, v in docs.items():
        c, tk = len(v), len(enc.encode(v))
        tot_c += c
        tot_t += tk
        rows.append((meta[k]["type"], k, c, tk, len(links.get(k, ()))))
    for typ in ("rule", "track"):
        sub = [r for r in rows if r[0] == typ]
        print(f"\n[{typ}] {len(sub)}건  글자 {sum(r[2] for r in sub):,}  토큰 {sum(r[3] for r in sub):,}")
        for _, k, c, tk, nl in sorted(sub, key=lambda r: -r[3]):
            print(f"  {tk:>7,} tok {c:>8,}자  links {nl:>2}  {k}")
    n_links = sum(len(v) for v in links.values()) // 2
    print(f"\n총 {len(docs)}건  글자 {tot_c:,}  토큰 {tot_t:,}  링크(무향) {n_links}")
    print(f"gpt-4o-mini 창 128,000 토큰 대비 {tot_t / 128000:.2f}배")
    lonely = [k for k in docs if k not in links]
    print("링크 없는 문서:", lonely or "없음")


if __name__ == "__main__":
    main()
