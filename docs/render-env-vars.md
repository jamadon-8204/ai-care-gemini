# Render 환경변수

Render 배포할 때 이 문서만 열어서 그대로 넣으면 된다.

## 꼭 넣을 것

### 1) 필수

```text
GOOGLE_API_KEY=여기에_구글_제미니_API_키
```

### 2) 저장까지 쓸 때

```text
SUPABASE_URL=여기에_슈퍼베이스_URL
SUPABASE_SERVICE_ROLE_KEY=여기에_슈퍼베이스_서비스_롤_키
```

## 있으면 좋은 것

```text
GEMINI_MODEL=gemini-2.5-flash-native-audio-latest
GEMINI_VOICE=Kore
APP_TIMEZONE=Asia/Seoul
APP_FAMILY_EXTERNAL_KEY=gajuni-default-family
APP_FAMILY_NAME=윤가준 가족
APP_CARE_RECIPIENT_EXTERNAL_KEY=gajuni-default-care-recipient
APP_CARE_RECIPIENT_FULL_NAME=가준이 할머니
APP_CARE_RECIPIENT_DISPLAY_NAME=할머니
```

## CORS

Render 배포 주소가 정해지면 그 주소를 넣는다.

예:

```text
CORS_ORIGINS=https://ai-care-gemini.onrender.com
```

로컬 개발까지 같이 열어두고 싶으면 쉼표로 같이 넣는다.

```text
CORS_ORIGINS=http://localhost:8000,https://ai-care-gemini.onrender.com
```

## 최소 배포 세트

처음 배포만 빨리 해보려면 이것만 넣어도 된다.

```text
GOOGLE_API_KEY=여기에_구글_제미니_API_키
GEMINI_MODEL=gemini-2.5-flash-native-audio-latest
GEMINI_VOICE=Kore
APP_TIMEZONE=Asia/Seoul
```

## 저장까지 포함한 권장 세트

```text
GOOGLE_API_KEY=여기에_구글_제미니_API_키
SUPABASE_URL=여기에_슈퍼베이스_URL
SUPABASE_SERVICE_ROLE_KEY=여기에_슈퍼베이스_서비스_롤_키
GEMINI_MODEL=gemini-2.5-flash-native-audio-latest
GEMINI_VOICE=Kore
CORS_ORIGINS=https://배포주소.onrender.com
APP_TIMEZONE=Asia/Seoul
APP_FAMILY_EXTERNAL_KEY=gajuni-default-family
APP_FAMILY_NAME=윤가준 가족
APP_CARE_RECIPIENT_EXTERNAL_KEY=gajuni-default-care-recipient
APP_CARE_RECIPIENT_FULL_NAME=가준이 할머니
APP_CARE_RECIPIENT_DISPLAY_NAME=할머니
```

## 어디서 열면 되나

서버가 켜져 있으면 여기서 바로 열 수 있다.

```text
http://localhost:8000/workspace/docs/render-env-vars.md
```

문서 목록:

```text
http://localhost:8000/workspace/docs
```
