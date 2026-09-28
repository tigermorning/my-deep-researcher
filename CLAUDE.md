# CLAUDE.md — my-deep-researcher

모두의연구소 9강 과제: 자막 규정·트랙을 대조하는 LangGraph 딥리서치 에이전트.

## 시작할 때

- **먼저 `HANDOFF.md`의 0절(시작 절차)과 9절(다음 할 일)을 읽는다.** 설계·실험 결과의 원본은 `REPORT.md`
- `git status --short --branch`로 깨끗한지 확인

## 꼭 지킬 것

- 자막·규정 원문은 저작물 — `data/corpus.json` · `data/raw/` · `output/runs/`(조사관 메모)는 커밋하지 않는다(.gitignore). 커밋 전 `git diff --cached --stat`
- API 키를 저장소에 올리지 않는다. 키는 환경변수 → `.env` → `~/Documents/openai_key.env`
- 제출은 저장소 **기본 URL만**(커밋·브랜치 고정 URL 금지)
- 문서는 개조식, 사용자에게는 한국어로 답한다
- **SDH 자막과 번역 자막을 "비교"하지 않는다.** 둘은 규칙 체계가 완전히 별개(SDH는 청각장애인용 표기 규칙, 번역은 번역 규칙)라 "SDH와 번역이 어떻게 다르게 처리하는가"류 질문 자체가 무효(2026-09-28 사용자 확인). **SDH를 번역의 "원문 대사 기준"으로 쓰는 것도 무효** — SDH도 SDH 규칙에 따라 가공된 결과물이라 원문 대사를 그대로 담은 신뢰할 기준이 아님. 새 질문·기능을 설계할 때 이 둘을 지킨다: (1) SDH는 SDH 규칙에만, 번역은 번역 규칙에만 맞는지 **각자 따로** 검사 (2) 번역이 정확한지 볼 땐 SDH가 아니라 원어 대사(스크립트·원문 트랙 등) 자체를 기준으로. 자세한 배경과 영향받는 기존 산출물은 `HANDOFF.md` "SDH·번역 비교 금지" 절 참고 — 이미 제출된 9강 산출물(q06, q07~q10)은 이 전제로 설계돼 있어 그대로 두되, 다음에 손댈 때는 이 규칙을 어기지 않는다

## 실행

- 한글 출력: `PYTHONIOENCODING=utf-8` 필수(Windows cp949)
- 한 질문 `python graph.py q03` · 대조군 `python baseline.py q03` · 절제 실험 `python ablation.py` · 데모 `streamlit run app.py`
- 코퍼스 빌드 `python scripts/build_corpus.py`(원본이 이 PC 로컬과 D 드라이브에만 있음)
- 파이썬 패치에 `\n` 같은 백슬래시가 들어가면 Bash heredoc 대신 Write 도구로 스크래치패드에 .py를 써서 돌린다
