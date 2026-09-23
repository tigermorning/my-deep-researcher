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

## 실행

- 한글 출력: `PYTHONIOENCODING=utf-8` 필수(Windows cp949)
- 한 질문 `python graph.py q03` · 대조군 `python baseline.py q03` · 절제 실험 `python ablation.py` · 데모 `streamlit run app.py`
- 코퍼스 빌드 `python scripts/build_corpus.py`(원본이 이 PC 로컬과 D 드라이브에만 있음)
- 파이썬 패치에 `\n` 같은 백슬래시가 들어가면 Bash heredoc 대신 Write 도구로 스크래치패드에 .py를 써서 돌린다
