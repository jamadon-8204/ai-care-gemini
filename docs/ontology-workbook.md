# 온톨로지 작업 노트

이 파일은 `바로 열어서 수정하는 실전용 파일`이다.
상세 설명은 [ontology-study-plan.md](/Users/jin/Downloads/gajoon ai care/mom care ai gemini/docs/ontology-study-plan.md)에 있고,
실제 결정은 이 파일에 적으면 된다.

## 한 줄 목표

어머니 대화에서 나오는 건강/생활 신호를
`같은 의미는 항상 같은 구조로 저장`할 수 있게 정의한다.

## 지금 우선순위

- [ ] 실제 대화 50턴 모으기
- [ ] 자주 나오는 개념 묶기
- [ ] 신호 사전 v1 만들기
- [ ] watch / urgent 기준 정하기
- [ ] 하루 요약 포맷 정하기

## 이번 주에 결정할 것

### 1. 핵심 개념 목록

아래에 실제로 반복 등장하는 개념만 적는다.

- 통증:
- 식사:
- 수면:
- 보청기:
- 활동:
- 농사:
- 어지럼:
- 낙상:
- 기분:
- 가족 연락 필요:
- 기타:

### 2. 구분 원칙

이 부분은 매우 중요하다.

- 관찰:
- 추론:
- 서비스 판단:

예시

- 관찰: "무릎이 아파"
- 추론: `pain_present = true`
- 판단: `risk_level = watch`

### 3. 불확실성 처리 원칙

- `unknown` 은 언제 쓰는가:
- `false` 는 언제 쓰는가:
- STT가 잘못 들린 것 같을 때는 어떻게 남기는가:
- 다시 물어본 턴은 어떻게 표시하는가:
- 사람이 나중에 수정하면 어디에 남기는가:

## 신호 사전 v1

아래 표를 직접 채우면 된다.

| 신호명 | 의미 | 허용값 | 언제 채움 | 언제 비움 | 예문 | 반례 |
|---|---|---|---|---|---|---|
| pain_present | 통증 여부 | true / false / null |  |  |  |  |
| pain_locations | 통증 부위 | 자유 텍스트 배열 |  |  |  |  |
| pain_severity | 통증 강도 | mild / moderate / severe |  |  |  |  |
| meal_status | 식사 상태 | good / reduced / poor / skipped |  |  |  |  |
| sleep_status | 수면 상태 | good / light / poor / insomnia / frequent_waking |  |  |  |  |
| hearing_aid_status | 보청기 상태 | wearing / not_wearing / sometimes |  |  |  |  |
| activity_status | 활동 상태 | normal / limited / unable / resting |  |  |  |  |
| farm_work_status | 농사 가능 여부 | possible / limited / unable |  |  |  |  |
| dizziness_present | 어지럼 여부 | true / false / null |  |  |  |  |
| fall_present | 낙상 여부 | true / false / null |  |  |  |  |
| needs_family_followup | 가족 확인 필요 | true / false |  |  |  |  |
| risk_level | 위험도 | normal / watch / urgent |  |  |  |  |
| note_summary | 자유 메모 | text |  |  |  |  |

## 동의어 / 표현 묶음

같은 의미로 묶을 말을 적는다.

### 통증

- 아파
- 쑤셔
- 결려
- 시큰해
- 저려
- 기타:

### 식사

- 밥 먹었어
- 조금 먹었어
- 못 먹었어
- 입맛 없어
- 기타:

### 수면

- 잘 잤어
- 설쳤어
- 자주 깼어
- 한숨도 못 잤어
- 기타:

### 어지럼 / 낙상

- 어지러워
- 핑 돌았어
- 넘어졌어
- 미끄러졌어
- 기타:

## 턴 / 하루 / 장기 구분

### 턴에서만 볼 것

- 예:

### 하루 요약에서 볼 것

- 예:

### 장기 추세에서 볼 것

- 예:

## watch / urgent 기준 초안

아직 완벽할 필요 없다.
처음에는 단순하게 적는다.

| 조건 | 등급 | 가족 알림 필요 | 메모 |
|---|---|---|---|
| 낙상 언급 | urgent | yes |  |
| 많이 어지럽다고 함 | watch 또는 urgent |  |  |
| 심한 통증 | watch |  |  |
| 식사를 거름 | watch |  |  |
| 움직이기 어렵다고 함 | watch |  |  |
| 가준이가 가족에게 전화하라고 말함 | urgent | yes |  |

## 하루 요약 포맷 초안

아래 문장을 직접 다듬는다.

### 가족에게 보여줄 한 줄 요약

-

### 핵심 항목

- 통증:
- 식사:
- 수면:
- 활동:
- 어지럼/낙상:
- 가족 확인 필요:

### 근거 문장 예시

- “”
- “”

## 잘 안 들린 사례 모음

여기는 STT 한계 때문에 꼭 모아야 한다.

| 날짜 | 원문 추정 | 전사 결과 | 문제 유형 | 메모 |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |

## 수정 이력

| 날짜 | 무엇을 바꿈 | 이유 |
|---|---|---|
|  |  |  |
|  |  |  |
|  |  |  |

## 다음 액션

- [ ] 대화 10턴만 먼저 넣어보기
- [ ] `pain_present`, `meal_status`, `sleep_status` 먼저 확정
- [ ] `watch`, `urgent` 기준 1차안 만들기
- [ ] 실제 가족에게 보여줄 요약 문장 3개 써보기
