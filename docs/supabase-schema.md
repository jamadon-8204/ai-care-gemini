# Supabase 스키마 초안

이 서비스의 핵심 자산은 모델이 아니라
`노인과 자연스럽게 대화하는 방식`, `건강/생활 신호를 구조화하는 기준`, `가족에게 전달할 요약 형식`이다.

## 설계 원칙

- 저장 기준은 `세션 -> 연결 -> 턴 -> 건강 신호 -> 하루 요약 -> 알림` 순서로 둔다.
- 현재 FastAPI/Gemini Live 구조에서는 `turn_complete` 시점을 한 턴 확정 시점으로 본다.
- 건강 신호는 `null = 언급 없음`, `false = 명시적 부정`, `true = 명시적 긍정`으로 해석한다.
- MVP에서는 원본 오디오는 저장하지 않고, 최종 전사와 구조화된 신호만 저장한다.
- 자동 재연결이 있으므로 `웹소켓 연결`과 `논리 세션`을 분리한다.

## 핵심 테이블

- `families`
  - 가족 단위 루트 엔티티다.
  - 타임존을 여기에 둬서 하루 요약 날짜 기준을 고정한다.
  - 배포별 기본 레코드를 자동 bootstrap 하려면 `external_key` 가 필요하다.

- `care_recipients`
  - 실제 대화 대상자다. 지금은 사실상 어머니 1명이다.
  - `prompt_profile` 에 가족 관계, 건강 배경, 말투 보정용 정보 조각을 넣을 수 있다.
  - 서버 초기 연결 시 `external_key` 기준 upsert 가 가능해야 한다.

- `family_contacts`
  - 아빠, 큰아빠 같은 가족 연락 대상을 저장한다.
  - 나중에 알림 우선순위와 수신 대상 제어에 쓴다.

- `device_installations`
  - 현재 프론트 `client_id` 를 여기에 대응시키면 된다.
  - 한 스마트폰 설치본을 식별하는 용도다.

- `conversation_sessions`
  - 버튼 한 번 눌러 시작한 논리 대화 세션이다.
  - 자동 재연결이 생겨도 `conversation_key` 하나로 묶는다.

- `session_connections`
  - 실제 웹소켓/Gemini 연결 단위다.
  - `go_away`, 재연결, 세션 복구 핸들 변화를 추적할 수 있다.

- `conversation_turns`
  - 사용자 한 번 말하고 가준이가 답한 최종 결과 한 묶음이다.
  - 현재 코드에서는 `turn_complete` 때 저장하면 된다.

- `turn_health_signals`
  - 턴에서 추출한 구조화된 건강/생활 신호다.
  - `conversation_turns` 와 1:1로 두되, 건강 정보가 없는 턴은 생성하지 않아도 된다.
  - 명시적 부정도 중요한 데이터이므로 `pain_present = false` 같은 값은 저장한다.

- `daily_summaries`
  - 하루 단위 요약 결과다.
  - 지금 당장 구현하지 않아도, 스키마는 미리 잡아 두면 나중에 안 흔들린다.

- `alert_events`
  - 가족 전달 필요 기준에 걸린 이벤트를 기록한다.
  - 실제 카카오 알림은 나중 단계에서 이 테이블을 기준으로 붙이면 된다.

## 건강 신호 필드 기준

- `pain_present`
  - `true`: 아프다고 함
  - `false`: 안 아프다고 명시
  - `null`: 통증 이야기가 안 나옴

- `pain_locations`
  - 예: `{"무릎","허리","팔"}`
  - 자유 텍스트 배열로 두고, 나중에 표준화가 필요하면 별도 사전 테이블을 붙인다.

- `pain_severity`
  - `mild`, `moderate`, `severe`
  - 자연어 대화에서는 숫자보다 3단계가 더 안정적이다.

- `meal_status`
  - `good`, `reduced`, `poor`, `skipped`

- `sleep_status`
  - `good`, `light`, `poor`, `insomnia`, `frequent_waking`

- `hearing_aid_status`
  - `wearing`, `not_wearing`, `sometimes`
  - 실제 착용 여부가 확인된 경우만 넣고, 단순히 잘 못 들었다는 이유만으로 추정하지 않는다.

- `activity_status`
  - `normal`, `limited`, `unable`, `resting`

- `farm_work_status`
  - `possible`, `limited`, `unable`
  - 농사 가능 여부를 별도로 분리해 두면 가족 요약 가치가 높다.

- `dizziness_present`, `fall_present`
  - 낙상/어지럼은 직접 알림 기준이 될 가능성이 높아서 boolean 으로 따로 둔다.

- `needs_family_followup`
  - 가족 전달 필요 여부다.
  - 실제 알림 전송 여부와는 분리해 둔다.

- `risk_level`
  - `normal`, `watch`, `urgent`
  - 요약과 알림 모두 이 값을 재사용한다.

- `note_summary`
  - 구조화되지 않는 짧은 메모다.
  - 예: `입맛 없다고 하시고 오늘은 밭에 안 나가셨음`

- `evidence`
  - 나중에 자동 추출 품질을 검토하기 위한 JSON 필드다.
  - 예: 사용자 문장, 근거 구절, 추출 버전, 수동 수정 이력.

## 저장 흐름 권장안

1. 프론트에서 `startSession()` 할 때 새 `conversation_key` 를 만든다.
2. 재연결 동안에는 같은 `conversation_key` 를 유지하고, `stopSession()` 때 폐기한다.
3. 서버에서 `client_id` 를 `device_installations.client_id` 에 매핑한다.
4. 서버는 `families`, `care_recipients`, `device_installations` 를 bootstrap/upsert 한다.
5. 첫 연결 시 `conversation_sessions` 를 생성한다.
6. 매 웹소켓 연결마다 `session_connections` 를 한 건 만든다.
7. `turn_complete` 시점에 최종 `user_transcript`, `assistant_transcript` 로 `conversation_turns` 를 저장한다.
8. 저장 직후 규칙 기반 또는 LLM 기반 추출기로 `turn_health_signals` 를 넣는다.
9. 하루 종료 배치 또는 수동 실행으로 `daily_summaries` 와 `alert_events` 를 만든다.

## 지금 코드와 바로 맞는 포인트

- 현재 `client_id` 는 이미 있으니 `device_installations` 와 바로 연결할 수 있다.
- 현재 프론트는 `startSession()` 때 `conversation_key` 를 만들고 재연결 동안 같은 값을 유지하도록 맞춰 두었다.
- 현재 서버는 사용자/가준이 전사를 버퍼링하다가 `turn_complete` 때 턴을 닫는다.
- 따라서 지금 단계에서는 `partial transcript` 저장보다 `final merged transcript` 저장이 우선이다.
- `needs_repeat_prompt`, `hearing_aid_prompted`, `family_call_prompted` 는 품질 분석과 위험 신호 기준 둘 다에 유용하다.
- 현재 구현은 규칙 기반 추출기로 `turn_health_signals` 를 기본 저장하고, 나중에 LLM 추출기로 교체하거나 병행할 수 있다.

## 다음 구현 순서

1. 실제 Supabase 프로젝트에 마이그레이션을 적용한다.
2. Render 환경변수에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 를 넣는다.
3. 실제 어머니 대화 데이터 1~2주치를 보고 규칙 기반 추출 정확도를 다듬는다.
4. 그다음 하루 요약과 알림 기준을 붙인다.
