# 자막 규정 딥리서처

넷플릭스·디즈니+·쿠팡플레이 자막 규정과 실제 자막 트랙을 맞대어 보는 오케스트레이터-워커 딥리서치 에이전트. 모두의연구소 9강 프로젝트.

- 코디네이터가 목차를 짜고 절마다 조사관(서브에이전트)을 붙인다
- 조사관은 자기 구역의 청크만 읽고 원고·인용·자기신고만 올린다(원문은 아래에 남는다)
- 부족하다고 신고한 절만 다시 보낸다
- 정답표·판정 모델 없이 코드로 지표를 잰다
- 설계·실험·실패 분석은 [REPORT.md](REPORT.md)
- 자료 출처: 작성자의 자막 도구 [subtitle-tc-generator](https://github.com/tigermorning/subtitle-tc-generator)를 만들며 모은 규정·자막(원문은 로컬 전용). 코드는 그 저장소에 의존하지 않는다

## 구조

```
기획 → 배치 → 조사관 ×N(병렬) → 점검 ─(부족 신고한 절)→ 배치
                                  └─(빈 칸 없음·바퀴 소진·재위임 꺼짐)→ 종합 → 평가
```

| 파일 | 하는 일 |
|---|---|
| `graph.py` | LangGraph 파이프라인(① 기획 ~ ⑥ 평가), CLI |
| `metrics.py` | 지표(경보 4 · 견줌 13). 지표마다 보는 장치를 `SPEC`에 적음. 인용 대조 검사(`quote_issues`)도 여기 — 조사관이 도구로 씀 |
| `baseline.py` | 혼자 하는 대조군(같은 자료·모델·도구·읽기 예산) |
| `ablation.py` | 스위치 하나씩 끈 설정 + 대조군을 여러 번 돌려 집계 |
| `app.py` | streamlit 데모 |
| `config.json` | 절 수 · 절 예산 · 기준 예산 · 바퀴 상한 · 청크 크기 · 스위치 · 역할 명단 |
| `data/questions.json` | 질문 12건(단일 2 · 흩어진 6 · 한 대상 4). 질문마다 `why` |
| `data/sources.json` | 코퍼스 수집 목록(본문 없음) |
| `data/corpus_index.json` | 코퍼스 색인: 60건의 제목·메타·글자 수·토큰 수·청크 수 + links 전체(본문 없음) |
| `data/sample_corpus.json` · `data/sample_questions.json` | 공개용 예시 코퍼스(전부 지어낸 자료 11건) + 질문 3건 |
| `scripts/make_sample_corpus.py` | 예시 코퍼스를 만드는 스크립트(대본·규정·심어 둔 어긋남이 여기 있음) |
| `scripts/build_corpus.py` | 로컬 원본 → `data/corpus.json` |
| `scripts/check_plans.py` | ① 기획만 12문항에 돌려 목차 검사 |
| `scripts/export_index.py` | `corpus.json` → `corpus_index.json`(본문 제외) |
| `scripts/capture_demo.py` | README용 데모 화면 캡처(지난 실행 두 장 · 실행 중 진행 표시 한 장) |
| `tests/test_review.py` | 가짜 LLM으로 그래프 전체를 돌려 ④ 점검(재위임·채택 규칙)을 시험 — API 호출 없음 |
| `hitl.py` | HITL 승인 게이트 — graph.py의 노드를 그대로 재사용하되 ⑥ 평가 뒤에 사람 승인(⑦)을 하나 더 붙인 별도 그래프(10강 프로젝트, REPORT.md 12절) |
| `hitl_app.py` | HITL streamlit 데모(승인 대기 목록 · 승인 화면 · 완료된 실행) |
| `tests/test_hitl.py` | 가짜 LLM으로 HITL 게이트(자동통과·승인·반려·수정후승인·대기 목록)를 시험 — API 호출 없음 |
| `output/` | `runs.jsonl` · `ablation.json` · `ablation.md` · `reports/` (v2, 118실행) |
| `output/v1/` | 첫 판 104실행 기록(고치기 전 비교용) |
| `output/sample/` | 예시 코퍼스 실행 결과(본 실험과 분리) |
| `output/hitl/` · `output/hitl_sample/` | HITL 데모 실행 결과 — 위 `output/`의 제출 실험 집계와 분리 |

## 무엇을 재현할 수 있나

- 자막·규정 원문은 저작물이라 **`data/corpus.json`을 저장소에 올리지 않았다** (과제 제출 구조의 `data/corpus.json` 자리)
- 저장소만 받아도 되는 것
  - 코퍼스 규모·링크 확인: `data/corpus_index.json` (60건 · 1,609,245자 · 836,287토큰 = 창 6.53배 · 링크 134)
  - 결과 보기: `output/`의 118실행(v2, `runs.jsonl` · `ablation.md` · `reports/`), `output/v1/`의 104실행(첫 판)과 데모 화면(`streamlit run app.py`, 코퍼스 없이 뜬다)
  - 지표 다시 계산은 코퍼스가 필요하다(청크 정보를 씀)
  - **파이프라인을 끝까지 직접 돌려 보기: 예시 코퍼스**(아래)
- 원본이 있어야 되는 것: 본 코퍼스 빌드와 본 실험 재실행(`graph.py` · `baseline.py` · `ablation.py`). 코퍼스가 없으면 `graph.py`가 이유를 알려 주고 멈춘다

### 예시 코퍼스로 끝까지 돌려 보기

- 무엇: 플랫폼 '예시플릭스' · 작품 2편(달빛 우체국 E01, 등대지기의 겨울 E03) · 트랙 5 · 규정 6. **플랫폼·작품·규정·대사 전부 지어낸 것**(실제 자막·규정 문장 없음)
  - 규정 수치(16자 · 초당 12자 · 42자 등)만 업계에서 흔히 쓰는 값을 빌림
  - 형식은 본 코퍼스와 같다(meta · docs · links, 트랙 첫 줄 메타 · 큐 한 줄 형식)
  - 트랙 2개는 8,000자를 넘어 청크가 둘로 나뉜다(청크 단위 배정·맞대기 보기까지 거침)
  - 트랙에 규정과 어긋나는 곳을 일부러 심어 둠 → 목록은 `sample_corpus.json`의 `_심어둔어긋남`
  - 심지 않은 어긋남(줄 길이 · 줄 수 · 읽기 속도 · 문장부호 · 괄호)은 생성 스크립트가 검사해 없앴다 → 이 목록이 정답표 구실
- 실행 (`--sample` 또는 환경변수 `DR_SAMPLE=1`, OpenAI 키 필요, gpt-4o-mini 한 질문 14~26호출)

```bash
PYTHONIOENCODING=utf-8 python graph.py s02 --sample
```

```bash
PYTHONIOENCODING=utf-8 python baseline.py s02 --sample
```

```bash
DR_SAMPLE=1 streamlit run app.py
```

- 질문: `s01` 단일(규정만) · `s02` 흩어진(SDH 트랙 둘 × 언어별 가이드) · `s03` 한 대상(강제 자막 ↔ SDH)
- 결과는 `output/sample/`에 저장 — 본 실험(`output/runs.jsonl` · `ablation.json`)과 섞이지 않는다. `ablation.py`는 예시 모드를 거부한다
- 예시 코퍼스 다시 만들기: `python scripts/make_sample_corpus.py`
- 실행 결과 — 두 판 모두 경보 0, 각 1회라 흔들림을 감안할 것
  - v1(첫 판, `output/sample/v1/`)
    - s02 팀: 심어 둔 어긋남(한국어 SDH 화자 소괄호 3 · 효과음 서술형 4 · 가사 `#` 1, 영어 SDH 소괄호 2)을 하나도 못 찾고 '규정에 부합'이라 씀
    - s02 대조군: 영어 SDH `(martha)` 소괄호 1건은 찾음. 대신 화자 `[RADIO VOICE]`를 효과음으로 잘못 봄
    - s03: 심어 둔 누락 2건(간판이 SDH에 없음 · 문자 메시지가 강제 자막에 없음)을 못 찾음
    - s01: 답은 맞지만 같은 조항 번호를 «강제 자막 규정»에도 달아 인용함
  - v2(표기 통계·인용 대조를 넣은 판, `output/sample/`) — REPORT 3절 'v2'
    - s02 팀: 효과음 서술형 어긋남을 짚음(표기 통계의 '서술형 [ ] 4개'를 씀). 다만 예로 든 큐가 틀렸고 화자 소괄호는 놓침
      - 리뷰 반영 전 같은 판으로 한 번 더 돌렸을 때는 셋(화자 소괄호 · 서술형 · 영어 효과음 소괄호)을 찾고, 영어 대문자 화자(규정대로)를 위반이라 함 → 시행마다 흔들림
    - s02 대조군: 전부 '규정에 부합'. 표기 통계의 '큐 총 180개'를 '큐 180'으로 옮겨 씀
    - s03: 문자 메시지 누락(SDH 큐 35 `[문자]`)을 이번에도 놓침
  - 읽는 법: 개수를 코드가 세어 주면 '있다·없다'는 맞아지지만, 어느 큐가 어긋났는지 짚는 것과 규정 해석은 그대로 약하다 — REPORT 9절
  - 예시는 작아서(13청크) 대조군도 거의 다 읽는다(예산소진율 50%) — 분업의 값(흩어진 자료 도달)이 드러나는 규모는 아니다

## 준비

- Python 3.12, 패키지

```bash
pip install langgraph openai tiktoken streamlit langgraph-checkpoint-sqlite
```

- `langgraph-checkpoint-sqlite`는 HITL 데모(아래 "HITL(사람 승인) 데모" 절)에만 쓴다. `graph.py`·`app.py`는 그대로다

- OpenAI 키: 환경변수 `OPENAI_API_KEY` → 저장소의 `.env` → `~/Documents/openai_key.env` 순으로 찾음
  - `.env`는 gitignore. 키를 저장소에 올리지 않음
  - 데모 화면에서는 옆 칸에 붙여 넣어도 됨(세션 안에서만 씀)
- 코퍼스: 자막·규정 원문은 저작물이라 저장소에 없음. 원본이 있는 PC에서 빌드

```bash
python scripts/build_corpus.py
```

- 끝에 `총 60건 … 링크 없는 문서: 없음`이 나오면 정상
- 60건 · 1,609,245자 · 836,287토큰 = gpt-4o-mini 창(128k)의 6.53배

## 실행

- 한 질문 (Windows 콘솔은 `PYTHONIOENCODING=utf-8` 필요)

```bash
PYTHONIOENCODING=utf-8 python graph.py q03
```

- 스위치 끄기 (`배정검사` · `남의구역` · `재위임` · `인용대조`)

```bash
PYTHONIOENCODING=utf-8 python graph.py q03 --off 남의구역
```

- 혼자 하는 대조군

```bash
PYTHONIOENCODING=utf-8 python baseline.py q03 --budget 18
```

- 절제 실험 (기본 5문항 × 6설정 × 3회 = 기본 · 스위치 넷 하나씩 끔 · 대조군)

```bash
PYTHONIOENCODING=utf-8 python ablation.py
```

- 나머지 문항을 기본 · 대조군만 돌려 기존 결과에 더하기

```bash
PYTHONIOENCODING=utf-8 python ablation.py --qs q02 q04 q05 q06 q08 q09 q12 --configs 기본 --reps 2 --replace
```

- 대조군만 다시 돌리기(팀 실행은 그대로, 예산·횟수는 기존 기본 실행에서) — 대조군 쪽 코드만 고쳤을 때

```bash
PYTHONIOENCODING=utf-8 python ablation.py --baseline-only --qs q01 q02 q03 q04 q05 q06 q07 q08 q09 q10 q11 q12
```

- 지표만 다시 계산(API 호출 없음, `runs.jsonl`도 다시 씀)

```bash
PYTHONIOENCODING=utf-8 python ablation.py --collect --recompute
```

- 데모

```bash
streamlit run app.py
```

- 테스트(API 호출 없음 · 예시 코퍼스 · 표준 `unittest`라 설치할 것 없음)

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

  - 가짜 LLM이 대본대로 답하고, 진짜 OpenAI 클라이언트는 부르면 바로 실패하게 막아 둠
  - 보는 것: 재작성본의 유효 인용이 줄거나 비면 지난 원고를 지킴(되돌림) · 늘면 새 원고 채택 · 바퀴 상한에서 멈춤 · 재위임 스위치를 끄면 실제로 1바퀴 · 가짜 실행도 ⑥ 평가까지 가고 호출 수가 가짜가 받은 수와 같음
  - 규칙을 일부러 망가뜨려(항상 덮어쓰기 · 스위치 무시 · 상한 없음 · 되돌릴 때 읽은 청크 안 넘김) 네 경우 모두 테스트가 실패하는 것을 확인함
  - `test_hitl.py`: 경보 없으면 자동 통과 · 바퀴 소진+부족 신고면 멈춤 · 승인/수정후승인/반려 세 갈래 · 대기 목록이 처리된 건을 빼는지

## HITL(사람 승인) 데모 (10강 프로젝트)

기존 파이프라인(위 "실행")은 그대로 두고, ⑥ 평가 뒤에 승인 게이트(⑦)를 하나 더 붙인 별도
그래프(`hitl.py`)로 돈다. 설계·승인 기준·실행 결과는 [REPORT.md 12절](REPORT.md#12-hitl사람-승인-게이트-10강-프로젝트).

```bash
streamlit run hitl_app.py
# 예시 코퍼스로: DR_SAMPLE=1 streamlit run hitl_app.py
```

- 왼쪽에서 질문을 골라 새로 실행 → 승인 기준(인용 위험 · 미흡 위험)에 안 걸리면 그대로
  `output/hitl/reports/`에 저장, 걸리면 "승인 대기" 탭에서 멈춘다
- 대기 중인 건을 열면: 질문 · 멈춘 이유 · 근거(문제 문장·부족 신고 사유) · AI가 쓴 보고서 초안 ·
  통과시키면 무슨 일이 일어나는지가 보이고, 승인 / 수정 후 승인 / 반려 / 다시 판정 중 하나를 고른다
- 저장 위치는 `output/hitl/`(예시 코퍼스는 `output/hitl_sample/`) — 제출 실험 집계(`output/reports/`·`output/runs.jsonl`)와 분리

## 데모 화면

- 지난 실행을 고르거나 새로 실행(질문 · 팀/대조군 · 스위치)
- 실행 중에는 LangGraph 스트리밍으로 진행을 바로 보여 줌: 노드가 끝날 때마다 로그, 조사관이 청크를 하나 읽을 때마다 절별 진행표(읽음/예산 · 방금 읽은 청크)
- 탭: 보고서 · 절마다 누가 무엇을(배정 → 읽은 순서 → 원고 → 부족 신고) · 기획(코드가 고친 것) · 지표 · 로그
- 캡처(streamlit을 띄운 상태에서, Playwright 필요)
  - 지난 실행: `python scripts/capture_demo.py <실행 이름>` — API 호출 없음
  - 진행 표시: `DR_SAMPLE=1 streamlit run app.py --server.port 8502` 뒤 `python scripts/capture_demo.py --progress s02 --port 8502` — 새 실행을 하나 돌림(예시 코퍼스 약 25호출)
- `?run=<실행 이름>`으로 특정 실행을 바로 연다

![데모 첫 화면](docs/demo.png)

![절마다 누가 무엇을](docs/demo_sections.png)

![실행 중 진행 표시(예시 코퍼스)](docs/demo_progress.png)

## 저작권·비밀

- 저장소에 올리지 않는 것: `data/corpus.json` · `data/raw/` · `output/runs/` · `output/v1/runs/`(조사관 메모 = 자막 발췌) · `.env`
- 예시 코퍼스와 그 실행 기록(`output/sample/runs/` 메모 포함)은 지어낸 자료라 올린다
- 보고서 속 자막 인용은 짧은 대사 단위
- HITL 체크포인터(`output/hitl*/checkpoints.sqlite*`)는 절마다 통째 State(자막 발췌 포함)를 담으므로 올리지 않는다 — `output/hitl/runs/*.json`은 승인 기록·로그·지표만 남겨(원문 발췌 제외) 올려도 된다
