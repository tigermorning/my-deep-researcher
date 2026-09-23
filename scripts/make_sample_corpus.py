# -*- coding: utf-8 -*-
"""공개용 예시 코퍼스(data/sample_corpus.json)와 예시 질문(data/sample_questions.json)을 만든다.

    python scripts/make_sample_corpus.py

- 내용은 전부 지어낸 것이다: 플랫폼 '예시플릭스', 작품 '달빛 우체국'·'등대지기의 겨울', 규정 6건, 대사 전부.
  실제 자막·규정 문장은 한 줄도 없다(원문은 저작물이라 저장소에 못 올림 — 채점자가 끝까지 돌려 볼 수 있게 대신 만든 것)
- 형식은 scripts/build_corpus.py가 만드는 data/corpus.json과 같다: meta · docs · links(무향, 코드 규칙) · _트랙형식
- 트랙에는 규정과 어긋나는 곳을 일부러 심어 두었다(아래 SEEDED). 조사팀이 찾아야 할 '정답 후보'이자 데모의 볼거리
  심지 않은 어긋남(줄 길이·줄 수·읽기 속도·큐 길이·문장부호·괄호)은 check()가 찾아 생성을 멈춘다 — SEEDED가 정답표 구실을 하게.
  효과음 서술형·화자 표기 여부처럼 코드로 못 재는 것은 대본을 사람이 확인했다
- 규정 문장은 새로 쓴 것이지만, 수치(16자·초당 12자·42자·초당 20자·5/6초·7초 등)는 업계에서 흔히 쓰는 값을 빌렸다
- 실행: DR_SAMPLE=1 python graph.py s02 (또는 python graph.py s02 --sample). 결과는 output/sample/
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
P = "예시플릭스"
LANG = {"ko": "한국어", "en": "영어"}
KIND = {"sdh": "SDH·CC(같은 언어)", "translation": "번역 자막", "forced": "강제 자막"}

# ---------------------------------------------------------------- 규정 (지어낸 것)
HEAD = "# {t}\n\nsource: (가상 예시 — 실제 규정 아님)\nedited_at: 2026-09-23\n\n"
RULES = {
    f"{P} 한국어 가이드 I. 번역 자막": ({"lang": "ko", "section": "translation"}, """
이 문서는 예시플릭스 한국어 번역 자막의 요구 사항이다. SDH는 II절을 본다.

## I-1. 줄 길이와 줄 수
- I-1.1 한 줄은 공백 포함 16자를 넘지 않는다.
- I-1.2 한 큐는 두 줄까지. 세 줄 큐는 쓰지 않는다.
- I-1.3 줄을 나눌 때는 의미 단위(조사·어미 뒤)에서 나눈다. 수식어와 꾸밈을 받는 말을 두 줄로 가르지 않는다.

## I-2. 읽기 속도와 길이
- I-2.1 읽기 속도는 초당 12자 이하(공백 제외)를 지킨다. 어린이 대상 작품은 초당 9자.
- I-2.2 한 큐는 최소 5/6초(0.833초), 최대 7초 동안 보인다.
- I-2.3 큐 사이 간격은 2프레임 이상 둔다.

## I-3. 번역 자막에 넣지 않는 것
- I-3.1 화자 이름 표기([마사] 같은 것)와 효과음 표기는 번역 자막에 넣지 않는다. 그것은 SDH의 일이다.
- I-3.2 화면 속 글자(편지·간판·문자 메시지)는 줄거리에 필요할 때만 옮기고, 강제 자막 규정을 따른다.
- I-3.3 노래 가사는 줄거리에 필요할 때만 옮기며, 옮기면 앞뒤를 ♪로 감싼다.

## I-4. 문장부호
- I-4.1 말줄임표는 '…'(한 글자) 하나로 쓴다. '...'(마침표 셋)은 쓰지 않는다.
- I-4.2 한 큐에 두 사람이 말하면 줄마다 앞에 '- '를 붙인다.
- I-4.3 문장 끝 마침표는 찍지 않는다. 물음표·느낌표는 찍는다.
"""),
    f"{P} 한국어 가이드 II. SDH": ({"lang": "ko", "section": "sdh"}, """
이 문서는 예시플릭스 한국어 SDH(청각 장애인용 자막)의 요구 사항이다. 줄 길이·읽기 속도·문장부호는 I절(I-1, I-2, I-4)을 그대로 따른다.

## II-1. 화자 표기
- II-1.1 화자가 화면에 보이지 않거나 누가 말하는지 헷갈릴 때만 화자를 적는다.
- II-1.2 화자는 대괄호로 적는다: [한봄]. 소괄호 (한봄)는 쓰지 않는다.
- II-1.3 이름을 모르는 인물은 역할로 적는다: [집배원], [라디오 속 남자].
- II-1.4 외국어 대사는 [사토, 일본어로]처럼 언어를 밝히고, 뜻은 강제 자막이 맡는다. SDH에는 뜻을 따로 옮기지 않는다.

## II-2. 효과음
- II-2.1 효과음은 대괄호에 넣는다.
- II-2.2 효과음은 명사형으로 끝낸다: [문 여는 소리], [빗소리]. 서술형([문을 연다])은 쓰지 않는다.
- II-2.3 대사와 효과음이 한 큐에 겹치면 효과음을 앞에 둔다.

## II-3. 음악
- II-3.1 가사가 들리면 줄 앞뒤를 ♪로 감싼다: ♪ 달이 뜨면 ♪. '#' 같은 다른 기호는 쓰지 않는다.
- II-3.2 가사 없는 음악은 분위기를 적는다: [잔잔한 음악], [긴장감 도는 음악].
- II-3.3 곡명을 알면 [조용히 흐르는 '봄편지']처럼 적는다.

## II-4. 화면 속 글자
- II-4.1 줄거리에 필요한 화면 속 글자는 SDH에도 넣는다. 강제 자막에 있는 화면 글자는 SDH에도 같은 문구로 있어야 한다.
"""),
    f"{P} 영어 가이드": ({"lang": "en", "section": None}, """
This fictional guide covers English subtitles on 예시플릭스 (example only, not a real style guide).

## E-1. Line length and reading speed
- E-1.1 Max 42 characters per line, two lines per event.
- E-1.2 Reading speed: up to 20 characters per second for adult content.

## E-2. SDH
- E-2.1 Speaker IDs go in brackets in UPPERCASE: [MARTHA]. Use them only when the speaker is off-screen or unclear.
- E-2.2 Sound effects go in lowercase brackets: [door creaks], [wind howling]. Do not use parentheses.
- E-2.3 Lyrics are wrapped with ♪ on both ends.
- E-2.4 Foreign dialogue: identify the language, e.g. [speaking Korean], and let forced narratives carry the meaning.

## E-3. Translation (non-SDH)
- E-3.1 No speaker IDs or sound effects in translation subtitles.
- E-3.2 Translate on-screen text only when it is plot-relevant, in the same event timing as the text appears.
- E-3.3 Use a single ellipsis character (…). Keep normal English punctuation.
"""),
    f"{P} 강제 자막 규정": ({"lang": None, "section": None}, """
이 문서는 예시플릭스 강제 자막(forced narrative)의 요구 사항이다. 언어와 무관하게 적용한다.

## F-1. 강제 자막이 맡는 것
- F-1.1 강제 자막은 SDH를 켜지 않은 시청자에게도 꼭 보여야 하는 것만 옮긴다: 외국어 대사, 그리고 본편 언어로 쓰였더라도 줄거리에 필요한 화면 속 글자(편지·간판·문자 메시지 — 손글씨·작은 글씨라 읽기 어려운 것).
- F-1.2 본편 언어로 된 일반 대사는 강제 자막에 넣지 않는다.
- F-1.3 줄거리에 필요한 화면 속 글자가 있는데 강제 자막에 없으면 누락이다.

## F-2. SDH와의 관계
- F-2.1 강제 자막에 있는 문구는 같은 회차 SDH에도 같은 문구·같은 시각으로 있어야 한다.
- F-2.2 외국어 대사는 SDH에 언어 표기만 남고, 뜻은 강제 자막에만 있을 수 있다.

## F-3. 모양
- F-3.1 화면 글자는 대괄호나 화자 표기 없이 글자만 적는다.
- F-3.2 강제 자막은 옮기는 글자가 화면에 보이는 동안 떠 있어야 한다(최대 7초).
"""),
    f"{P} 일반 요구사항": ({"lang": None, "section": None, "보조": True}, """
이 문서는 예시플릭스 모든 언어 자막의 공통 요구 사항이다(가상 예시).

## G-1. 파일
- G-1.1 자막 파일은 회차별 하나, 문자 인코딩은 UTF-8.
- G-1.2 큐 번호는 1부터 빠짐없이 매긴다.

## G-2. 타이밍
- G-2.1 큐는 말소리 시작보다 앞서지 않는다. 장면 전환을 넘기지 않는다.
- G-2.2 큐는 겹치지 않는다.

## G-3. 언어별 가이드
- G-3.1 언어별 가이드가 이 문서와 다르면 언어별 가이드를 따른다.
"""),
    "예시 작업 메모: 효과음 표기 예시": ({"lang": "ko", "section": None, "보조": True}, """
이 문서는 한국어 SDH 작업자가 모아 둔 효과음 표기 예시다(가상 예시). 규정이 아니라 참고용이다.

## 자주 쓰는 표기
- 문: [문 여는 소리], [문 닫히는 소리], [문 두드리는 소리]
- 날씨: [빗소리], [바람 소리], [천둥소리]
- 사람: [한숨], [웃음소리], [헛기침]
- 기계: [휴대폰 진동], [자전거 벨 소리], [도장 찍는 소리]

## 피할 표기
- [문을 두드린다] → [문 두드리는 소리] (서술형 대신 명사형)
- (웃음) → [웃음소리] (소괄호 대신 대괄호)
"""),
}

# ---------------------------------------------------------------- 트랙 대본 (지어낸 것)
# 항목: ("d", 화자, 한국어, 영어, 표지) 대사 · ("d2", (화자,한,영), (화자,한,영)) 두 사람 한 큐
#       ("s", 효과음) · ("m", 음악 설명) · ("l", 가사) · ("t", 화면 글자 종류, 한국어, 영어, 표지) · ("f", 화자, 뜻(한), 뜻(영)) 외국어
#       ("gap", 초) 장면 사이
# 표지: id = 화면 밖 화자라 SDH에 [화자] · paren = SDH에 소괄호로 잘못 적음 · verb = 효과음을 서술형으로 잘못 적음
#       hash = 가사를 #로 잘못 감쌈 · long_en = 영어 번역 줄이 42자 넘음 · noforced = 화면 글자가 강제 자막에서 빠짐
#       nosdh = 화면 글자가 SDH에서 빠짐
SEEDED = [
    "달빛 우체국 E01 한국어 SDH: 화자 소괄호 3곳(II-1.2), 효과음 서술형 4곳(II-2.2), 가사 # 1곳(II-3.1), 간판 글자 빠짐 1곳(II-4.1·F-2.1)",
    "달빛 우체국 E01 한국어 강제 자막: 문자 메시지 화면 글자 빠짐 1곳(F-1.3)",
    "달빛 우체국 E01 영어 번역: 42자 넘는 줄 2곳(E-1.1)",
    "등대지기의 겨울 E03 영어 SDH: 화자 소괄호·소문자 1곳(E-2.1), 효과음 소괄호 1곳(E-2.2), 42자 넘는 줄 1곳(E-1.1)",
    "등대지기의 겨울 E03 한국어 번역: 16자 넘는 줄 3곳(I-1.1), 화자 표기 남음 1곳(I-3.1), 마침표 셋 말줄임 1곳(I-4.1)",
]

MOON = [
    ("m", "잔잔한 음악"),
    ("s", "자전거 벨 소리"),
    ("t", "간판", "달빛 우체국 / 1974년 개국", "MOONLIGHT POST OFFICE / EST. 1974", "nosdh"),
    ("d", "한봄", "오늘도 편지는 / 세 통뿐이네", "Only three letters / again today", ""),
    ("d", "문 국장", "세 통도 많아", "Three is a lot around here", "id"),
    ("d", "한봄", "국장님, 언제 오셨어요?", "When did you get here, sir?", ""),
    ("d", "문 국장", "방금, 커피 남았나?", "Just now. Any coffee left?", ""),
    ("d", "한봄", "보리차밖에 없어요", "Only barley tea", ""),
    ("d", "문 국장", "그럼 보리차라도", "Barley tea it is, then", ""),
    ("s", "문 여는 소리"),
    ("d", "도윤", "배달 다녀왔습니다!", "I'm back from my route!", ""),
    ("d", "한봄", "벌써요? / 윗마을까지 갔다 왔어요?", "Already? / You went all the way uphill?", ""),
    ("d", "도윤", "자전거 체인이 끊겨서 / 걸어서 갔다 왔지", "The bike chain snapped, / so I walked the whole way", "long_en"),
    ("d", "문 국장", "그 자전거 / 나보다 나이 많아", "That bike is / older than me", ""),
    ("d2", ("도윤", "그럼 새로 사 주세요", "Then buy me a new one"), ("문 국장", "예산이 없어", "No budget")),
    ("d", "한봄", "순례 할머니 댁 편지는요?", "What about Grandma Sunrye's letter?", ""),
    ("d", "도윤", "그게… / 할머니가 안 계셨어", "Well… / she wasn't home", ""),
    ("d", "한봄", "이 시간에 / 어딜 가셨지?", "Where would she go / at this hour?", ""),
    ("m", "긴장감 도는 음악"),
    ("gap", 40),
    ("s", "바람 소리"),
    ("d", "한봄", "할머니! / 순례 할머니!", "Grandma! / Grandma Sunrye!", ""),
    ("d", "순례", "여기 있어, 여기", "Over here, over here", "id"),
    ("d", "한봄", "밭에 계셨어요?", "You were in the field?", ""),
    ("d", "순례", "편지 왔어? / 우리 아들 편지?", "Is there a letter? / From my son?", ""),
    ("d", "한봄", "네, 서울에서 왔어요", "Yes, it came from Seoul", ""),
    ("s", "봉투 뜯는 소리", "verb:[봉투를 뜯는다]"),
    ("t", "편지", "어머니, 올겨울엔 / 꼭 내려갈게요", "Mom, I'll come home / this winter for sure", ""),
    ("d", "순례", "눈이 침침해서 / 네가 좀 읽어 줘", "My eyes are bad. / Read it for me", ""),
    ("d", "한봄", "'어머니, 올겨울엔 / 꼭 내려갈게요'", "\"Mom, I'll come home / this winter for sure\"", ""),
    ("s", "한숨"),
    ("d", "순례", "작년에도 / 그렇게 썼어", "He wrote the same / last year", ""),
    ("d", "한봄", "이번엔 진짜일 거예요", "This time he means it", ""),
    ("d", "순례", "봄이 너는 / 말도 참 예쁘게 해", "You always say / such kind things, Bom", ""),
    ("m", "따뜻한 음악"),
    ("gap", 35),
    ("s", "휴대폰 진동"),
    ("t", "문자", "폐국 검토 회의 / 금요일 오후 3시", "Meeting on closing the post office / Friday 3 p.m.", "noforced"),
    ("d", "한봄", "폐국이요?", "Closing?", ""),
    ("d", "문 국장", "아직 검토야, 검토", "It's only a review", ""),
    ("d", "한봄", "국장님은 / 알고 계셨어요?", "You knew / about this?", ""),
    ("d", "문 국장", "한 달 전에 들었어", "I heard a month ago", ""),
    ("d", "한봄", "왜 말씀 안 하셨어요?", "Why didn't you tell me?", ""),
    ("d", "문 국장", "네가 이렇게 / 볼 줄 알았으니까", "Because I knew you'd / look at me like that", ""),
    ("s", "문 닫히는 소리"),
    ("d", "도윤", "봄아, 무슨 일이야?", "Bom, what's going on?", "paren"),
    ("d", "한봄", "우체국이 / 없어질 수도 있대", "They might / close the post office", ""),
    ("d", "도윤", "여기가 없어지면 / 할머니들 편지는?", "If it closes, / what about the grandmas' mail?", ""),
    ("d", "한봄", "읍내까지 / 버스 타고 가야지", "They'd have to take / the bus to town", ""),
    ("d", "도윤", "버스는 / 하루 두 번인데", "The bus only comes / twice a day", ""),
    ("m", "쓸쓸한 음악"),
    ("gap", 50),
    ("s", "빗소리"),
    ("f", "사토", "실례합니다 / 우체국이 여기인가요?", "Excuse me. / Is this the post office?"),
    ("d", "한봄", "네? / 아, 네, 우체국이에요", "Sorry? / Oh, yes, this is it", ""),
    ("f", "사토", "이 엽서를 / 일본으로 보내고 싶어요", "I'd like to send / this postcard to Japan"),
    ("d", "도윤", "일본으로 / 보내신대", "He wants to send it / to Japan", ""),
    ("d", "한봄", "항공우편으로 / 해 드릴게요", "I'll send it / by airmail", ""),
    ("f", "사토", "할아버지가 / 이 마을에 사셨어요", "My grandfather / lived in this village"),
    ("d", "한봄", "할아버지가요?", "Your grandfather?", ""),
    ("t", "엽서", "1974년 여름, / 달빛 우체국 앞에서", "Summer 1974, / in front of Moonlight Post Office", ""),
    ("d", "문 국장", "이 사진… / 우리 우체국 개국 날이야", "This photo… / it's our opening day", ""),
    ("d", "문 국장", "가운데 계신 분이 / 초대 국장님이고", "The man in the middle / was the first postmaster", ""),
    ("d", "한봄", "옆에 계신 분은요?", "And the man beside him?", ""),
    ("d", "문 국장", "모르겠는데", "No idea", ""),
    ("d2", ("도윤", "할머니는 아시려나?", "Maybe Grandma knows?"), ("한봄", "내일 여쭤보자", "Let's ask her tomorrow")),
    ("s", "천둥소리"),
    ("m", "신비로운 음악"),
    ("gap", 45),
    ("s", "새소리"),
    ("d", "순례", "이 사람…", "This man…", ""),
    ("d", "순례", "기요시야, 기요시", "It's Kiyoshi. Kiyoshi", ""),
    ("d", "한봄", "아세요?", "You know him?", ""),
    ("d", "순례", "여름마다 우체국 앞에서 / 그림을 그렸지", "Every summer / he painted pictures / in front of the post office", "long_en"),
    ("d", "순례", "편지를 / 참 많이 부쳤어", "He mailed / so many letters", ""),
    ("d", "한봄", "누구한테요?", "To whom?", ""),
    ("s", "헛기침"),
    ("d", "순례", "그건 비밀", "That's a secret", ""),
    ("d", "도윤", "할머니 / 얼굴 빨개지셨어요", "Grandma, / you're blushing", "paren"),
    ("d", "순례", "더워서 그래, 더워서", "It's just the heat", ""),
    ("s", "웃음소리"),
    ("gap", 30),
    ("l", "달이 뜨면 편지를 써요"),
    ("l", "당신 계신 곳까지", "hash"),
    ("d", "한봄", "국장님, 이 노래 / 뭐예요?", "Sir, what's / this song?", ""),
    ("d", "문 국장", "개국 기념식 때 / 부른 노래야", "We sang it at / the opening ceremony", ""),
    ("d", "문 국장", "초대 국장님이 / 가사를 쓰셨지", "The first postmaster / wrote the lyrics", ""),
    ("d", "한봄", "이 노래로 / 뭔가 할 수 있을 것 같아요", "I think we could / do something with this song", ""),
    ("d", "문 국장", "무슨 생각인데?", "What are you thinking?", ""),
    ("d", "한봄", "마을 사람들 편지를 / 모아서 전시하는 거예요", "We collect the villagers' letters / and put on an exhibit", ""),
    ("d", "한봄", "우체국이 / 왜 필요한지 보여 주는 거죠", "To show why / the post office matters", ""),
    ("d", "문 국장", "회의가 금요일이야", "The meeting's on Friday", ""),
    ("d", "한봄", "그럼 나흘 남았네요", "Then we have four days", ""),
    ("s", "도장 찍는 소리", "verb:[도장을 쾅 찍는다]"),
    ("m", "경쾌한 음악"),
    ("gap", 40),
    ("s", "자전거 벨 소리"),
    ("d", "도윤", "윗마을 다섯 집, / 편지 다 받아 왔어", "Five houses uphill, / I got all their letters", ""),
    ("d", "한봄", "아랫마을은 / 내가 받아 왔어", "I got the ones / from downhill", ""),
    ("d", "도윤", "이거 봐, / 1980년 편지도 있어", "Look, / there's one from 1980", ""),
    ("d", "한봄", "군대 간 아들한테 / 보낸 편지네", "It's to a son / in the army", ""),
    ("d", "도윤", "답장도 있어", "There's a reply too", ""),
    ("t", "편지", "어머니, 여기 밥은 / 어머니 밥만 못해요", "Mom, the food here / isn't as good as yours", ""),
    ("d", "한봄", "다들 / 이렇게 살았구나", "So this is / how everyone lived", ""),
    ("d", "도윤", "봄아, 이거 / 기요시 씨 편지 아니야?", "Bom, isn't this / one of Kiyoshi's letters?", ""),
    ("d", "한봄", "받는 사람이…", "The recipient is…", ""),
    ("t", "봉투", "받는 사람: 박순례", "To: Park Sunrye", ""),
    ("d2", ("도윤", "할머니잖아!", "It's Grandma!"), ("한봄", "쉿, 조용히", "Shh, quiet")),
    ("m", "설레는 음악"),
    ("gap", 35),
    ("d", "순례", "그걸 / 어디서 찾았어?", "Where did you / find that?", ""),
    ("d", "한봄", "할머니 댁 / 광에서요", "In your / storage shed", ""),
    ("d", "순례", "버린 줄 알았는데", "I thought I'd thrown it out", ""),
    ("d", "한봄", "전시에 / 써도 될까요?", "May we use it / in the exhibit?", ""),
    ("d", "순례", "…써", "…Go ahead", ""),
    ("d", "순례", "그 사람도 / 좋아할 거야", "He would / have liked that", ""),
    ("s", "바람 소리"),
    ("gap", 40),
    ("s", "라디오 소리"),
    ("d", "라디오 진행자", "오늘 밤부터 / 첫눈이 내리겠습니다", "The first snow / will fall tonight", "id"),
    ("d", "한봄", "첫눈 오면 / 전시 못 하는 거 아니에요?", "If it snows, / can we still hold the exhibit?", ""),
    ("d", "문 국장", "우체국은 / 눈 와도 문 열어", "The post office / opens even in snow", ""),
    ("d", "도윤", "배달은 / 제가 하는 거잖아요", "But I'm the one / doing deliveries", ""),
    ("d", "문 국장", "그러니까 / 자전거 조심하라고", "So be careful / on that bike", ""),
    ("d", "도윤", "체인 끊긴 / 자전거 말씀이세요?", "You mean the bike / with the broken chain?", ""),
    ("s", "한숨"),
    ("d", "한봄", "국장님, 벽에 걸 / 액자가 모자라요", "Sir, we don't have / enough frames", ""),
    ("d", "문 국장", "창고에 / 옛날 액자 있을 거야", "There should be / old frames in storage", ""),
    ("d", "한봄", "창고 열쇠는요?", "Where's the storage key?", ""),
    ("d", "문 국장", "서랍 두 번째 칸", "Second drawer", ""),
    ("s", "서랍 여는 소리"),
    ("d", "한봄", "열쇠가 / 세 개나 있는데요", "There are / three keys here", ""),
    ("d", "문 국장", "제일 녹슨 거", "The rustiest one", ""),
    ("s", "자물쇠 여는 소리"),
    ("d", "도윤", "와, 여기 / 먼지가 장난 아니다", "Wow, it's / really dusty in here", ""),
    ("d", "한봄", "저기 상자 좀 / 내려 줄래?", "Can you get / that box down?", ""),
    ("d", "도윤", "무거운데… / 뭐가 들었지?", "It's heavy… / what's in it?", ""),
    ("s", "상자 떨어지는 소리", "verb:[상자가 바닥에 떨어진다]"),
    ("d", "한봄", "괜찮아?", "Are you okay?", ""),
    ("d", "도윤", "괜찮아 / 근데 이거 봐", "I'm fine. / But look at this", ""),
    ("d", "한봄", "옛날 우편 가방이네", "It's an old mailbag", ""),
    ("d", "도윤", "안에 / 편지가 들어 있어", "There are / letters inside", ""),
    ("d", "한봄", "배달 못 한 / 편지들인가 봐", "They must be letters / that were never delivered", ""),
    ("t", "소인", "1975년 1월 3일", "JAN 3, 1975", ""),
    ("d", "문 국장", "그해 겨울 / 폭설이 왔었지", "That winter / there was a blizzard", "id"),
    ("d", "문 국장", "길이 막혀서 / 한 달 동안 배달을 못 했어", "The roads were blocked / and we couldn't deliver for a month", ""),
    ("d", "한봄", "그럼 이 편지들은 / 오십 년 동안…", "So these letters / have been here fifty years…", ""),
    ("d", "문 국장", "여기서 / 기다린 거지", "Waiting / right here", ""),
    ("m", "애잔한 음악"),
    ("gap", 35),
    ("s", "눈 밟는 소리"),
    ("d", "도윤", "봄아, 주소 확인해 봤어", "Bom, I checked the addresses", ""),
    ("d", "도윤", "받는 사람 / 절반은 아직 마을에 살아", "Half the recipients / still live in the village", ""),
    ("d", "한봄", "그럼 / 지금이라도 전해 드리자", "Then let's / deliver them now", ""),
    ("d", "도윤", "오십 년 늦은 배달이네", "A delivery fifty years late", ""),
    ("d", "한봄", "늦어도 / 배달은 배달이지", "Late or not, / a delivery is a delivery", ""),
    ("s", "문 두드리는 소리", "verb:[문을 두드린다]"),
    ("d", "마을 할아버지", "누구요?", "Who is it?", "id"),
    ("d", "도윤", "우체국에서 왔습니다", "It's the post office", ""),
    ("d", "마을 할아버지", "이 눈에 / 무슨 우편이야?", "Mail in / this snow?", ""),
    ("d", "도윤", "1975년에 / 보내신 편지요", "A letter sent / in 1975", ""),
    ("s", "문 여는 소리"),
    ("d", "마을 할아버지", "이건… / 우리 형 글씨야", "This is… / my brother's handwriting", ""),
    ("d", "마을 할아버지", "형은 그해 봄에 / 바다에서 돌아오지 못했어", "My brother never came back / from the sea that spring", ""),
    ("d", "도윤", "…죄송합니다", "…I'm sorry", ""),
    ("d", "마을 할아버지", "아니야", "No", ""),
    ("d", "마을 할아버지", "고맙네, 젊은이", "Thank you, young man", ""),
    ("s", "울음소리"),
    ("m", "잔잔한 음악"),
    ("gap", 40),
    ("s", "웅성거리는 소리"),
    ("d", "문 국장", "자, 조용히들 하시고", "All right, everyone, quiet down", ""),
    ("d", "문 국장", "오늘 전시는 / 봄이가 준비했습니다", "Bom put together / today's exhibit", ""),
    ("d", "한봄", "이 편지들은 / 전부 이 우체국을 거쳤어요", "Every one of these letters / passed through this office", ""),
    ("d", "한봄", "오십 년 동안요", "For fifty years", ""),
    ("d", "심사관", "감동적이긴 한데요", "It's moving, but", "id"),
    ("d", "심사관", "숫자로 보면 / 하루 평균 세 통이에요", "In numbers, / it's three letters a day", ""),
    ("d", "한봄", "세 통이면 / 많은 거예요", "Three is / a lot", ""),
    ("d", "한봄", "여기서는요", "Around here", ""),
    ("s", "박수 소리"),
    ("l", "달이 뜨면 편지를 써요"),
    ("l", "당신 계신 곳까지"),
    ("f", "사토", "할아버지의 편지를 / 가져왔습니다", "I brought my / grandfather's letters"),
    ("d", "순례", "기요시…", "Kiyoshi…", "paren"),
    ("m", "벅찬 음악"),
    ("gap", 30),
    ("d", "문 국장", "결정은 / 다음 달에 난대", "The decision / comes next month", ""),
    ("d", "한봄", "그래도 / 해 볼 건 다 했어요", "At least / we did everything we could", ""),
    ("d", "도윤", "자전거는 / 언제 사 주세요?", "So when do I / get a new bike?", ""),
    ("d", "문 국장", "예산이 없대도", "I told you, no budget", ""),
    ("s", "웃음소리"),
    ("m", "잔잔한 음악"),
]

HARBOR = [
    ("s", "wind howling", "바람 소리"),
    ("s", "foghorn blaring", "무적 소리"),
    ("d", "Martha", "Eli, shut that door / before the lamp goes out", "엘리, 문 닫아 / 등불 꺼지겠다", ""),
    ("d", "Eli", "It's freezing in here", "여기 너무 추워요", ""),
    ("d", "Martha", "It's a lighthouse, / not a hotel", "등대야 / 호텔이 아니고", ""),
    ("s", "door slams", "문 닫히는 소리"),
    ("d", "Eli", "How long have you / lived here, Aunt Martha?", "여기 사신 지 / 얼마나 되셨어요?", ""),
    ("d", "Martha", "Thirty-one winters", "서른한 번째 겨울이야", ""),
    ("d", "Eli", "Alone?", "혼자서요?", ""),
    ("d", "Martha", "With the lamp", "등불이랑 같이", ""),
    ("s", "radio static", "무전기 잡음"),
    ("d", "Radio Voice", "Harbor station to keeper, / storm coming in tonight", "항만국에서 등대지기에게 / 오늘 밤 폭풍이 옵니다", "id"),
    ("d", "Martha", "Copy that, / we'll keep the light on", "알았다 / 불은 계속 켜 두겠다", ""),
    ("d", "Eli", "Is it going to be bad?", "많이 심할까요?", ""),
    ("d", "Martha", "They always say that. / Most nights it's fine", "늘 그렇게 말해 / 대부분은 괜찮아", "long_en"),
    ("m", "tense music", "긴장감 도는 음악"),
    ("gap", 40),
    ("s", "thunder rumbling", "천둥소리"),
    ("d", "Eli", "The light's flickering!", "등불이 깜빡여요!", ""),
    ("d", "Martha", "Get the spare bulb / from the second drawer", "두 번째 서랍에서 / 예비 전구를 꺼내 와", "id_bad"),
    ("d", "Eli", "Which drawer?", "어느 서랍이요?", ""),
    ("d", "Martha", "The second one, Eli!", "두 번째 서랍이라니까 엘리야, 빨리!", "ko_long"),
    ("s", "glass breaking", "유리 깨지는 소리", "paren_sfx"),
    ("d", "Eli", "I'm sorry, / I dropped it", "죄송해요 / 떨어뜨렸어요", ""),
    ("d", "Martha", "Then we use / the old oil lamp", "그럼 옛날 / 기름 등을 쓰자", ""),
    ("d", "Eli", "That thing still works?", "그게 아직도 돼요?", ""),
    ("d", "Martha", "It worked for my father", "우리 아버지 때도 멀쩡히 잘만 됐어", "ko_long"),
    ("s", "match striking", "성냥 긋는 소리"),
    ("m", "gentle music", "잔잔한 음악"),
    ("gap", 45),
    ("s", "waves crashing", "파도 소리"),
    ("d", "Eli", "Aunt Martha… / there's a boat out there", "이모… / 저기 배가 있어요", "ko_ellipsis"),
    ("d", "Martha", "Give me the binoculars", "쌍안경 줘", ""),
    ("d", "Martha", "It's the Sullivans' boat. / They're heading for the rocks", "설리번네 배야 / 암초 쪽으로 가고 있어", "ko_long"),
    ("d", "Eli", "What do we do?", "어떡해요?", ""),
    ("d", "Martha", "We swing the light / toward the channel", "등불을 / 뱃길 쪽으로 돌린다", ""),
    ("s", "metal creaking", "쇠 삐걱거리는 소리"),
    ("d", "Martha", "Push, Eli! Push!", "밀어, 엘리! 밀어!", ""),
    ("d", "Eli", "It's moving!", "움직여요!", ""),
    ("s", "foghorn blaring", "무적 소리"),
    ("d", "Radio Voice", "Keeper, this is Sullivan. / We see your light", "등대지기, 설리번이다 / 불빛이 보인다", "id"),
    ("d", "Radio Voice", "We're turning back. / Thank you", "돌아가겠다 / 고맙다", "id"),
    ("s", "Eli laughing", "엘리가 웃는 소리"),
    ("d", "Eli", "We did it!", "해냈어요!", ""),
    ("d", "Martha", "The lamp did it", "등불이 해낸 거야", "ko_speaker"),
    ("m", "hopeful music", "희망찬 음악"),
    ("gap", 30),
    ("l", "Keep the light burning, / keep the harbor near", "불을 켜 두렴 / 항구가 멀지 않게"),
    ("d", "Eli", "Is that your song?", "그거 이모 노래예요?", ""),
    ("d", "Martha", "My father's. / He sang it every storm", "아버지 노래야 / 폭풍 때마다 부르셨지", ""),
    ("d", "Eli", "Can you teach me?", "저도 가르쳐 주세요", ""),
    ("d", "Martha", "Next winter. / If you come back", "내년 겨울에 / 다시 오면", ""),
    ("s", "wind howling", "바람 소리"),
]


def tc(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def moon_texts():
    """대본 → 트랙별 [(항목 번호, 자막 글, 심은 어긋남인가)]. 시각은 나중에 모든 트랙 글을 보고 정한다."""
    sdh, forced, en = [], [], []
    for i, it in enumerate(MOON):
        k = it[0]
        if k == "d":
            _, who, ko, eng, flag = it
            if flag == "id":
                sdh.append((i, f"[{who}] {ko}", False))
            elif flag == "paren":
                sdh.append((i, f"({who}) {ko}", True))
            else:
                sdh.append((i, ko, False))
            if flag == "long_en":
                en.append((i, eng.replace(" / ", " "), True))   # 두 줄을 붙여 42자를 넘긴다
            else:
                en.append((i, eng, False))
        elif k == "d2":
            (_, k1, e1), (_, k2, e2) = it[1], it[2]
            sdh.append((i, f"- {k1} / - {k2}", False))
            en.append((i, f"- {e1} / - {e2}", False))
        elif k == "s":
            bad = it[2][5:] if len(it) > 2 and it[2].startswith("verb:") else None
            sdh.append((i, bad or f"[{it[1]}]", bool(bad)))
        elif k == "m":
            sdh.append((i, f"[{it[1]}]", False))
        elif k == "l":
            hashed = len(it) > 2 and it[2] == "hash"
            sdh.append((i, f"# {it[1]} #" if hashed else f"♪ {it[1]} ♪", hashed))
        elif k == "t":
            _, what, ko, eng, flag = it
            if flag != "nosdh":
                sdh.append((i, f"[{what}] {ko}", False))
            if flag != "noforced":
                forced.append((i, ko, False))
            en.append((i, eng, False))
        elif k == "f":
            _, who, ko, eng = it
            sdh.append((i, f"[{who}, 일본어로]", False))
            forced.append((i, ko, False))
            en.append((i, eng, False))
    return {"sdh": sdh, "forced": forced, "en": en}


def harbor_texts():
    sdh, ko = [], []
    for i, it in enumerate(HARBOR):
        k = it[0]
        if k == "d":
            _, who, eng, kor, flag = it
            if flag == "id":
                sdh.append((i, f"[{who.upper()}] {eng}", False))
            elif flag == "id_bad":
                sdh.append((i, f"({who.lower()}) {eng}", True))
            elif flag == "long_en":
                sdh.append((i, eng.replace(" / ", " "), True))
            else:
                sdh.append((i, eng, False))
            if flag == "ko_long":
                ko.append((i, kor.replace(" / ", " "), True))     # 두 줄을 한 줄로 붙여 16자를 넘긴다
            elif flag == "ko_ellipsis":
                ko.append((i, kor.replace("…", "..."), True))
            elif flag == "ko_speaker":
                ko.append((i, f"[마사] {kor}", True))
            else:
                ko.append((i, kor, False))
        elif k == "s":
            bad = len(it) > 3 and it[3] == "paren_sfx"
            sdh.append((i, f"({it[1]})" if bad else f"[{it[1]}]", bad))
        elif k == "m":
            sdh.append((i, f"[{it[1]}]", False))
        elif k == "l":
            sdh.append((i, " / ".join(f"♪ {x} ♪" for x in it[1].split(" / ")), False))
            ko.append((i, " / ".join(f"♪ {x} ♪" for x in it[2].split(" / ")), False))
    return {"sdh": sdh, "ko": ko}


def _chars(text, lang):
    """읽기 속도에 세는 글자 수 — 한국어는 공백 제외(I-2.1), 영어는 공백 포함(E-1.2). 줄바꿈 표시 ' / '는 뺀다."""
    t = text.replace(" / ", "")
    return len(t.replace(" ", "")) if lang == "ko" else len(t)


CPS = {"ko": 12, "en": 20}


def timeline(script, tracks, langs, start=31.5):
    """항목마다 (시작, 끝). 트랙끼리 같은 시각을 쓰므로, 그 항목을 싣는 모든 트랙 글이 읽기 속도를 지키는 길이로 잡는다."""
    need = {}
    for key, rows in tracks.items():
        for i, text, _ in rows:
            need[i] = max(need.get(i, 1.2), _chars(text, langs[key]) / (CPS[langs[key]] - 1))   # 1자 여유
    t, out = start, {}
    for i, it in enumerate(script):
        if it[0] == "gap":
            t += it[1]
            continue
        dur = min(7.0, need.get(i, 1.2))
        out[i] = (t, t + dur)
        t += dur + (1.0 if it[0] == "s" else 0.5)
    return out


def check(title, lang, kind, rows, times):
    """심지 않은 규정 어긋남을 찾는다 — 있으면 _심어둔어긋남 목록이 정답표 구실을 못 한다."""
    bad = []
    width = 16 if lang == "ko" else 42
    for n, (i, text, seeded) in enumerate(rows, 1):
        if seeded:
            continue
        a, b = times[i]
        lines = text.split(" / ")
        why = []
        if len(lines) > 2:
            why.append("세 줄")
        why += [f"{len(x)}자 줄" for x in lines if len(x) > width]
        if _chars(text, lang) / (b - a) > CPS[lang]:
            why.append(f"초당 {_chars(text, lang) / (b - a):.1f}자")
        if not 0.833 <= b - a <= 7:
            why.append(f"{b - a:.2f}초")
        if "..." in text:
            why.append("마침표 셋")
        if lang == "ko" and any(x.endswith(".") for x in lines):
            why.append("문장 끝 마침표")
        if "(" in text:
            why.append("소괄호")
        if kind == "translation" and "[" in text:
            why.append("번역에 대괄호 표기")
        if why:
            bad.append(f"{title} 큐 {n} {text!r}: {', '.join(why)}")
    return bad


def render(header, rows, times):
    return header + "\n" + "\n".join(f"{n}\t{tc(times[i][0])} --> {tc(times[i][1])}\t{text}"
                                      for n, (i, text, _) in enumerate(rows, 1))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    docs, meta = {}, {}
    links = defaultdict(set)

    def link(a, b):
        if a != b:
            links[a].add(b)
            links[b].add(a)

    for title, (m, body) in RULES.items():
        docs[title] = HEAD.format(t=title) + body.strip() + "\n"
        meta[title] = {"type": "rule", "platform": P, "source_id": "sample", **m}

    unseeded = []

    def add_track(work, ep, track, orig, lang, kind, rows, times):
        title = f"{work} {ep} {track}"
        header = (f"[작품 원어: {LANG[orig]} | 자막 언어: {LANG[lang]} | 종류: {KIND[kind]} | 플랫폼: {P}]")
        docs[title] = render(header, rows, times)
        meta[title] = {"type": "track", "work": work, "platform": P, "ep": ep, "track": track,
                       "orig_lang": orig, "lang": lang, "kind": kind, "cues": len(rows)}
        unseeded.extend(check(title, lang, kind, rows, times))
        return title

    mt = moon_texts()
    mt_times = timeline(MOON, mt, {"sdh": "ko", "forced": "ko", "en": "en"})
    m_sdh = add_track("달빛 우체국", "E01", "한국어 SDH", "ko", "ko", "sdh", mt["sdh"], mt_times)
    m_forced = add_track("달빛 우체국", "E01", "한국어 강제 자막", "ko", "ko", "forced", mt["forced"], mt_times)
    m_en = add_track("달빛 우체국", "E01", "영어 번역", "ko", "en", "translation", mt["en"], mt_times)
    ht = harbor_texts()
    ht_times = timeline(HARBOR, ht, {"sdh": "en", "ko": "ko"})
    h_sdh = add_track("등대지기의 겨울", "E03", "영어 SDH", "en", "en", "sdh", ht["sdh"], ht_times)
    h_ko = add_track("등대지기의 겨울", "E03", "한국어 번역", "en", "ko", "translation", ht["ko"], ht_times)
    if unseeded:
        raise SystemExit("심지 않은 규정 어긋남 — 대본을 고칠 것:\n" + "\n".join(unseeded))

    # --- links: build_corpus.py와 같은 규칙 ---
    g_tr, g_sdh, g_en = f"{P} 한국어 가이드 I. 번역 자막", f"{P} 한국어 가이드 II. SDH", f"{P} 영어 가이드"
    forced_rule, general, sfx = f"{P} 강제 자막 규정", f"{P} 일반 요구사항", "예시 작업 메모: 효과음 표기 예시"
    link(g_tr, g_sdh)                                  # 같은 가이드의 절끼리
    for g in (g_tr, g_sdh, g_en):                      # 언어별 가이드 ↔ 일반 요구사항
        link(g, general)
    link(sfx, g_sdh)
    link(forced_rule, g_tr)                            # 번역 가이드 I-3.2가 강제 자막 규정을 가리킴
    tracks = [k for k, m in meta.items() if m["type"] == "track"]
    for a in tracks:
        ma = meta[a]
        for b in tracks:                               # 같은 작품의 다른 트랙
            if meta[b]["work"] == ma["work"]:
                link(a, b)
        if ma["lang"] == "ko":                         # 트랙 → 플랫폼·언어·종류에 맞는 규정
            link(a, g_sdh if ma["kind"] == "sdh" else g_tr)
        else:
            link(a, g_en)
        if ma["lang"] == "ko" and ma["kind"] == "sdh":
            link(a, sfx)
        if ma["kind"] == "forced":
            link(a, forced_rule)

    corpus = {
        "_설명": "공개용 예시 코퍼스 — 플랫폼·작품·규정·대사 전부 지어낸 것(실제 자막·규정 문장 없음). scripts/make_sample_corpus.py가 만든다",
        "_심어둔어긋남": SEEDED,
        "_트랙형식": "큐 한 줄 = 번호<TAB>시작 --> 끝<TAB>1행 / 2행",
        "meta": meta,
        "docs": docs,
        "links": {k: sorted(v) for k, v in sorted(links.items())},
    }
    for k in links:
        assert k in docs, k
    (DATA / "sample_corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")

    questions = {
        "_설명": "예시 코퍼스(data/sample_corpus.json)용 질문. 형식은 data/questions.json과 같다",
        "questions": [
            {"id": "s01", "type": "single",
             "question": f"{P} 한국어 번역 자막의 한 줄 최대 글자 수와 읽기 속도 기준은 무엇인가?",
             "docs": [g_tr],
             "why": "나눌 필요 없음(일부러 넣음). 번역 가이드 I절 한 건에 답이 있다"},
            {"id": "s02", "type": "scattered",
             "question": (f"{P} SDH 트랙 둘(달빛 우체국 E01 한국어 SDH, 등대지기의 겨울 E03 영어 SDH)의 "
                          "화자·효과음·음악 표기는 각 언어 가이드의 SDH 규정과 맞는가?"),
             "docs": [m_sdh, h_sdh, g_sdh, g_en],
             "why": "작품·언어·규정이 둘로 갈린다 — 트랙마다 조사관 하나씩"},
            {"id": "s03", "type": "tracking",
             "question": ("달빛 우체국 E01 한국어 강제 자막은 어느 대사·화면 글자에 붙었고, 같은 회차 한국어 SDH와 견주면 "
                          f"무엇이 빠지거나 더해졌는가? {P} 강제 자막 규정에 비춰 보라."),
             "docs": [m_forced, m_sdh, forced_rule],
             "why": "강제 자막 큐가 회차 전체에 흩어져 있어 SDH의 같은 시각 구간을 맞대야 한다"},
        ],
    }
    (DATA / "sample_questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding="utf-8")

    for k, v in docs.items():
        print(f"{len(v):>7,}자  links {len(links[k]):>2}  {k}" + (f"  (큐 {meta[k]['cues']})" if meta[k]["type"] == "track" else ""))
    print(f"\n총 {len(docs)}건 · {sum(map(len, docs.values())):,}자 · 링크(무향) {sum(map(len, links.values())) // 2}"
          " → data/sample_corpus.json, data/sample_questions.json")


if __name__ == "__main__":
    main()
