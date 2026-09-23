# -*- coding: utf-8 -*-
"""data/corpus.json(로컬 전용) → data/corpus_index.json(저장소에 올림).

본문은 빼고 제목 · 메타 · 글자 수 · 토큰 수 · 청크 수 · links만 남긴다.
자막·규정 원문은 저작물이라 저장소에 올리지 않는다 — 대신 이 색인으로
'몇 건인지 · 창을 넘는지 · 서로 어떻게 가리키는지'를 누구나 확인할 수 있게 한다.

    python scripts/export_index.py
"""
import json
import sys
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.argv = [sys.argv[0]]
import graph as g  # noqa: E402  (청크 수를 파이프라인과 같은 규칙으로 센다)

enc = tiktoken.get_encoding("o200k_base")
corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
docs = {}
for title, text in corpus["docs"].items():
    docs[title] = {**corpus["meta"][title], "chars": len(text), "tokens": len(enc.encode(text)),
                   "chunks": len(g.DOC_CHUNKS[title])}
total_chars = sum(d["chars"] for d in docs.values())
total_tokens = sum(d["tokens"] for d in docs.values())
index = {
    "_설명": "corpus.json에서 본문만 뺀 색인. 원문(자막·규정)은 저작물이라 저장소에 없다 — scripts/build_corpus.py로 로컬에서 만든다",
    "_수집일": corpus.get("_수집일"),
    "합계": {"문서": len(docs), "규정": sum(d["type"] == "rule" for d in docs.values()),
             "트랙": sum(d["type"] == "track" for d in docs.values()), "글자": total_chars,
             "토큰(o200k_base)": total_tokens, "gpt-4o-mini 창 대비": round(total_tokens / 128000, 2),
             "청크": len(g.CHUNKS), "링크(무향)": sum(len(v) for v in corpus["links"].values()) // 2,
             "링크 없는 문서": [t for t in docs if not corpus["links"].get(t)]},
    "docs": docs,
    "links": corpus["links"],
}
out = ROOT / "data" / "corpus_index.json"
out.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(f"{out.relative_to(ROOT)}: {index['합계']}")
