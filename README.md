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
| `metrics.py` | 지표(경보 4 · 견줌 11). 지표마다 보는 장치를 `SPEC`에 적음 |
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
| `scripts/capture_demo.py` | README용 데모 화면 캡처 |
| `output/` | `runs.jsonl` · `ablation.json` · `ablation.md` · `reports/` |
| `output/sample/` | 예시 코퍼스 실행 결과(본 실험과 분리) |

## 무엇을 재현할 수 있나

- 자막·규정 원문은 저작물이라 **`data/corpus.json`을 저장소에 올리지 않았다** (과제 제출 구조의 `data/corpus.json` 자리)
- 저장소만 받아도 되는 것
  - 코퍼스 규모·링크 확인: `data/corpus_index.json` (60건 · 1,609,245자 · 836,287토큰 = 창 6.53배 · 링크 134)
  - 결과 보기: `output/`의 104실행(`runs.jsonl` · `ablation.md` · `reports/`)과 데모 화면(`streamlit run app.py`, 코퍼스 없이 뜬다)
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
- 실행 결과(2026-09-23, `output/sample/`, 각 1회 · 경보 전부 0)
  - s02 팀: 심어 둔 어긋남(한국어 SDH 화자 소괄호 3 · 효과음 서술형 4 · 가사 `#` 1, 영어 SDH 소괄호 2)을 하나도 못 찾고 '규정에 부합'이라 씀. SDH 규정을 짝 번역 트랙에 들이댐(규정 적용 오류). 재위임 1회
  - s02 대조군: 영어 SDH `(martha)` 소괄호 1건은 찾음. 대신 화자 `[RADIO VOICE]`를 효과음으로 잘못 봄
  - s03: 강제 자막 ↔ SDH 짝은 맞게 댔지만 심어 둔 누락 2건(간판이 SDH에 없음 · 문자 메시지가 강제 자막에 없음)은 못 찾음
  - s01: 답(16자 · 초당 12자 · 두 줄 · 5/6~7초)은 맞지만 같은 조항 번호를 «강제 자막 규정»에도 달아 인용함
  - 본 실험에서 본 약점(규정 적용 오류 · 번호는 맞고 출처가 틀린 인용 · 안 본 것)이 예시 코퍼스에서도 그대로 나온다 — REPORT 9절
  - 예시는 작아서(13청크) 대조군도 거의 다 읽는다(12청크, 예산소진율 50%) — 분업의 값(흩어진 자료 도달)이 드러나는 규모는 아니다

## 준비

- Python 3.12, 패키지

```bash
pip install langgraph openai tiktoken streamlit
```

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

- 스위치 끄기 (`배정검사` · `남의구역` · `재위임`)

```bash
PYTHONIOENCODING=utf-8 python graph.py q03 --off 남의구역
```

- 혼자 하는 대조군

```bash
PYTHONIOENCODING=utf-8 python baseline.py q03 --budget 18
```

- 절제 실험 (기본 5문항 × 5설정 × 3회)

```bash
PYTHONIOENCODING=utf-8 python ablation.py
```

- 나머지 문항을 기본 · 대조군만 돌려 기존 결과에 더하기

```bash
PYTHONIOENCODING=utf-8 python ablation.py --qs q02 q04 q05 q06 q08 q09 q12 --configs 기본 --reps 2 --replace
```

- 지표만 다시 계산(API 호출 없음, `runs.jsonl`도 다시 씀)

```bash
PYTHONIOENCODING=utf-8 python ablation.py --collect --recompute
```

- 데모

```bash
streamlit run app.py
```

## 데모 화면

- 지난 실행을 고르거나 새로 실행(질문 · 팀/대조군 · 스위치)
- 탭: 보고서 · 절마다 누가 무엇을(배정 → 읽은 순서 → 원고 → 부족 신고) · 기획(코드가 고친 것) · 지표 · 로그
- 캡처: `python scripts/capture_demo.py <실행 이름>` (streamlit을 띄운 상태에서, Playwright 필요)
- `?run=<실행 이름>`으로 특정 실행을 바로 연다

![데모 첫 화면](docs/demo.png)

![절마다 누가 무엇을](docs/demo_sections.png)

## 저작권·비밀

- 저장소에 올리지 않는 것: `data/corpus.json` · `data/raw/` · `output/runs/`(조사관 메모 = 자막 발췌) · `.env`
- 예시 코퍼스와 그 실행 기록(`output/sample/runs/` 메모 포함)은 지어낸 자료라 올린다
- 보고서 속 자막 인용은 짧은 대사 단위
