# 가준이 v2

어머니가 스마트폰에서 버튼 하나로 AI 손자 "가준이"와 한국어 음성 대화를 할 수 있게 만든 FastAPI + Gemini Live API 웹앱이다.

## 구성

- `server.py`: FastAPI 백엔드, 브라우저와 Gemini Live API 사이 WebSocket 브리지
- `static/index.html`: 단일 파일 프런트엔드
- `static/manifest.json`: 홈 화면 추가용 PWA 설정
- `static/service-worker.js`: 기본 오프라인 셸 캐시
- `supabase/migrations/20260327090000_initial_schema.sql`: 초기 Supabase 스키마 초안
- `docs/supabase-schema.md`: 저장 구조와 건강 신호 기준 문서

## 현재 구현된 기능

- `/` 헬스체크
- `/session` 세션/오디오 설정 정보 확인
- `/ws` 실시간 음성 브리지
- 16kHz PCM 업로드, 24kHz PCM 재생
- 사용자/가준이 트랜스크립션 표시
- 버튼 1개로 연결/종료
- 안정성 우선 반이중 대화 흐름
- 기본 재연결 처리
- Live API 세션 복구 핸들 메모리 저장
- Supabase 연동 시 세션/연결/턴/기본 건강 신호 저장

## 아직 미구현

- 외부 저장소 기반 세션 복구 핸들 공유
- 운영용 인증/접근 제어
- 하루 요약 생성
- 가족 알림 전송

## 로컬 실행

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

브라우저에서 `http://localhost:8000/` 로 접속한다.

## 환경변수

- `GOOGLE_API_KEY`: Gemini API 키
- `SUPABASE_URL`: 나중에 대화 저장 연결 시 사용
- `SUPABASE_SERVICE_ROLE_KEY`: 백엔드에서 Supabase 저장 시 사용할 서버 전용 키
- `GEMINI_MODEL`: 기본값 `gemini-2.5-flash-native-audio-latest`
- `GEMINI_VOICE`: 기본값 `Kore`
- `CORS_ORIGINS`: 쉼표 구분 허용 도메인 목록

프런트는 직접 Supabase 에 접근하지 않으므로 anon key 는 현재 필요 없다.

옵션 기본값:

- `APP_TIMEZONE`: 기본값 `Asia/Seoul`
- `APP_FAMILY_EXTERNAL_KEY`: 기본값 `gajuni-default-family`
- `APP_FAMILY_NAME`: 기본값 `윤가준 가족`
- `APP_CARE_RECIPIENT_EXTERNAL_KEY`: 기본값 `gajuni-default-care-recipient`
- `APP_CARE_RECIPIENT_FULL_NAME`: 기본값 `가준이 할머니`
- `APP_CARE_RECIPIENT_DISPLAY_NAME`: 기본값 `할머니`

## 모델명 참고

요구사항에 맞춰 기본값은 `gemini-2.5-flash-native-audio-latest` 로 두었다.
다만 2026-03-25에 확인한 Google 공식 Live API 문서 예시는 `gemini-2.5-flash-native-audio-preview-12-2025` 를 사용한다.
배포 환경에서 `latest` 별칭이 동작하지 않으면 `GEMINI_MODEL` 환경변수로 공식 문서 모델명을 직접 지정하면 된다.

## 세션 관리 참고

- Google 공식 문서 기준으로 오디오 전용 세션은 기본 15분 제한이 있다.
- 연결 자체는 약 10분 전후로 종료될 수 있다.
- 이 프로젝트는 `context_window_compression` 과 `session_resumption` 을 함께 켜서 끊김 영향을 줄이는 방식으로 구성했다.
- 현재 세션 복구 핸들은 서버 메모리에만 저장되므로 재배포나 인스턴스 교체 시 이어지지 않는다.
