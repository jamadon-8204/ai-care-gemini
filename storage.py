import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from prompting import PROMPT_VERSION, merge_prompt_profile


logger = logging.getLogger("gajuni.storage")

DEFAULT_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Seoul").strip() or "Asia/Seoul"
DEFAULT_FAMILY_EXTERNAL_KEY = (
    os.getenv("APP_FAMILY_EXTERNAL_KEY", "gajuni-default-family").strip()
    or "gajuni-default-family"
)
DEFAULT_FAMILY_NAME = os.getenv("APP_FAMILY_NAME", "윤가준 가족").strip() or "윤가준 가족"
DEFAULT_CARE_RECIPIENT_EXTERNAL_KEY = (
    os.getenv("APP_CARE_RECIPIENT_EXTERNAL_KEY", "gajuni-default-care-recipient").strip()
    or "gajuni-default-care-recipient"
)
DEFAULT_CARE_RECIPIENT_FULL_NAME = (
    os.getenv("APP_CARE_RECIPIENT_FULL_NAME", "가준이 할머니").strip() or "가준이 할머니"
)
DEFAULT_CARE_RECIPIENT_DISPLAY_NAME = (
    os.getenv("APP_CARE_RECIPIENT_DISPLAY_NAME", "할머니").strip() or "할머니"
)
SIGNAL_EXTRACTION_VERSION = "rule-v1"

PAIN_LOCATION_KEYWORDS = {
    "머리": ("머리", "머리가", "두통"),
    "목": ("목", "목이"),
    "어깨": ("어깨", "어깨가"),
    "팔": ("팔", "팔이"),
    "손": ("손", "손이", "손목"),
    "허리": ("허리", "허리가"),
    "등": ("등", "등이"),
    "배": ("배", "배가", "속이"),
    "가슴": ("가슴", "가슴이"),
    "다리": ("다리", "다리가"),
    "무릎": ("무릎", "무릎이"),
    "발": ("발", "발이", "발목"),
    "관절": ("관절",),
}

PAIN_POSITIVE_PATTERNS = (
    r"아프",
    r"아파",
    r"쑤시",
    r"저리",
    r"결리",
    r"시큰",
    r"찌릿",
    r"통증",
)
PAIN_NEGATIVE_PATTERNS = (
    r"안\s*아파",
    r"안아파",
    r"안\s*아프",
    r"괜찮아",
    r"멀쩡해",
)
DIZZINESS_POSITIVE_PATTERNS = (r"어지러", r"빙빙", r"현기증")
DIZZINESS_NEGATIVE_PATTERNS = (r"안\s*어지", r"안어지")
FALL_POSITIVE_PATTERNS = (r"넘어졌", r"넘어질", r"쓰러졌", r"미끄러졌", r"낙상")
FALL_NEGATIVE_PATTERNS = (r"안\s*넘어", r"안넘어", r"안\s*쓰러")
REPEAT_PROMPT_PATTERNS = (
    r"잘 못 들었",
    r"다시 한번 말씀해",
    r"다시 말씀해",
)
HEARING_AID_PROMPT_PATTERNS = (r"보청기",)
FAMILY_CALL_PROMPT_PATTERNS = (
    r"아빠에게\s*바로\s*전화",
    r"바로\s*전화해",
)


class SupabaseStorageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        table: Optional[str] = None,
        status_code: Optional[int] = None,
        raw_body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.table = table
        self.status_code = status_code
        self.raw_body = raw_body


def parse_supabase_error_category(
    *,
    status_code: int,
    table: str,
    error_body: str,
) -> tuple[str, str]:
    category = "unknown"
    message = f"Supabase request failed: {status_code} {error_body}"

    if status_code == 404 and "PGRST205" in error_body:
        category = "missing_schema"
        message = (
            f"Supabase schema is missing required table '{table}'. "
            "Apply the SQL migration before enabling storage."
        )

    return category, message


def has_supabase_storage() -> bool:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return bool(url and key and "your_supabase" not in url and "your_supabase" not in key)


def normalize_text(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def resolve_timezone_name() -> str:
    try:
        ZoneInfo(DEFAULT_TIMEZONE)
        return DEFAULT_TIMEZONE
    except ZoneInfoNotFoundError:
        return "UTC"


def to_signal_date(value: datetime) -> str:
    timezone_name = resolve_timezone_name()
    return value.astimezone(ZoneInfo(timezone_name)).date().isoformat()


def contains_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def detect_boolean_signal(
    text: str,
    positive_patterns: tuple[str, ...],
    negative_patterns: tuple[str, ...],
) -> Optional[bool]:
    has_negative = contains_any_pattern(text, negative_patterns)
    has_positive = contains_any_pattern(text, positive_patterns)

    if has_negative and not has_positive:
        return False
    if has_positive:
        return True
    return None


def detect_meal_status(text: str) -> Optional[str]:
    if re.search(r"(밥|식사).*(안 했|안했|안 먹|안먹|거른)", text) or re.search(r"굶", text):
        return "skipped"
    if re.search(r"(밥|식사).*(못 먹|거의 못 먹)", text) or re.search(r"입맛(이)? 없", text):
        return "poor"
    if re.search(r"(조금|좀|반만|덜).*(먹|먹었)", text):
        return "reduced"
    if re.search(r"(밥|식사).*(먹었|했어|했어요|잘 먹)", text) or re.search(r"잘 먹었", text):
        return "good"
    return None


def detect_sleep_status(text: str) -> Optional[str]:
    if re.search(r"한숨도 못 잤", text) or re.search(r"잠(이)? 안 와", text):
        return "insomnia"
    if re.search(r"자주 깼", text) or re.search(r"계속 깼", text) or re.search(r"몇 번 깼", text):
        return "frequent_waking"
    if re.search(r"잠을 설쳤", text) or re.search(r"못 잤", text) or re.search(r"뒤척", text):
        return "poor"
    if re.search(r"선잠", text) or re.search(r"얕게 잤", text):
        return "light"
    if re.search(r"잘 잤", text) or re.search(r"푹 잤", text):
        return "good"
    return None


def detect_hearing_aid_status(text: str) -> Optional[str]:
    if not re.search(r"보청기", text):
        return None
    if re.search(r"보청기.*(안|못).*(꼈|껴|차|찼)", text) or re.search(r"안\s*꼈", text):
        return "not_wearing"
    if re.search(r"가끔.*보청기", text) or re.search(r"자주 안 끼", text):
        return "sometimes"
    if re.search(r"보청기.*(꼈|껴|차|찼|하고)", text) or re.search(r"끼고 있", text):
        return "wearing"
    return None


def detect_activity_status(text: str) -> Optional[str]:
    if re.search(r"못 움직", text) or re.search(r"움직이기 힘들", text):
        return "unable"
    if re.search(r"쉬고 있", text) or re.search(r"누워 있", text):
        return "resting"
    if re.search(r"불편", text) or re.search(r"힘들", text) or re.search(r"천천히", text):
        return "limited"
    if re.search(r"괜찮", text) or re.search(r"잘 움직", text):
        return "normal"
    return None


def detect_farm_work_status(text: str) -> Optional[str]:
    if re.search(r"(농사|밭).*(못|못해|못 했|못했|안 나가|안나가)", text):
        return "unable"
    if re.search(r"(농사|밭).*(조금|잠깐|살짝)", text):
        return "limited"
    if re.search(r"(농사|밭).*(했|하고|나갔|다녀왔)", text):
        return "possible"
    return None


def detect_pain_severity(text: str) -> Optional[str]:
    if re.search(r"(많이|너무|엄청|심해|몹시).*(아프|아파|쑤시|저리|결리|시큰)", text):
        return "severe"
    if re.search(r"(조금|좀|살짝|약간).*(아프|아파|쑤시|저리|결리|시큰)", text):
        return "mild"
    if contains_any_pattern(text, PAIN_POSITIVE_PATTERNS):
        return "moderate"
    return None


def detect_pain_locations(text: str) -> list[str]:
    locations: list[str] = []
    for label, keywords in PAIN_LOCATION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            locations.append(label)
    return locations


def extract_turn_flags(assistant_text: Optional[str]) -> dict[str, bool]:
    text = assistant_text or ""
    return {
        "needs_repeat_prompt": contains_any_pattern(text, REPEAT_PROMPT_PATTERNS),
        "hearing_aid_prompted": contains_any_pattern(text, HEARING_AID_PROMPT_PATTERNS),
        "family_call_prompted": contains_any_pattern(text, FAMILY_CALL_PROMPT_PATTERNS),
    }


def add_note(parts: list[str], value: Optional[str]) -> None:
    if value:
        parts.append(value)


def build_note_summary(payload: dict[str, Any]) -> Optional[str]:
    notes: list[str] = []
    pain_present = payload.get("pain_present")
    pain_locations = payload.get("pain_locations") or []
    pain_severity = payload.get("pain_severity")
    meal_status = payload.get("meal_status")
    sleep_status = payload.get("sleep_status")
    hearing_aid_status = payload.get("hearing_aid_status")
    activity_status = payload.get("activity_status")
    farm_work_status = payload.get("farm_work_status")

    if pain_present is True:
        pain_note = "통증 있음"
        if pain_locations:
            pain_note += f" ({', '.join(pain_locations)})"
        if pain_severity == "severe":
            pain_note += ", 심함"
        elif pain_severity == "mild":
            pain_note += ", 약함"
        add_note(notes, pain_note)
    elif pain_present is False:
        add_note(notes, "통증 없다고 말씀하심")

    meal_notes = {
        "good": "식사 상태 괜찮음",
        "reduced": "식사량 줄었다고 하심",
        "poor": "식사 상태 안 좋음",
        "skipped": "식사를 거르셨다고 하심",
    }
    add_note(notes, meal_notes.get(meal_status))

    sleep_notes = {
        "good": "잠은 괜찮다고 하심",
        "light": "잠을 설쳤다고 하심",
        "poor": "잠을 잘 못 주무셨다고 하심",
        "insomnia": "잠이 안 온다고 하심",
        "frequent_waking": "자주 깨셨다고 하심",
    }
    add_note(notes, sleep_notes.get(sleep_status))

    hearing_aid_notes = {
        "wearing": "보청기 착용 중",
        "not_wearing": "보청기 미착용",
        "sometimes": "보청기를 가끔만 착용",
    }
    add_note(notes, hearing_aid_notes.get(hearing_aid_status))

    activity_notes = {
        "normal": "움직임은 괜찮다고 하심",
        "limited": "움직임이 불편하다고 하심",
        "unable": "움직이기 어렵다고 하심",
        "resting": "쉬고 계신다고 하심",
    }
    add_note(notes, activity_notes.get(activity_status))

    farm_notes = {
        "possible": "농사나 밭일 가능",
        "limited": "농사나 밭일을 조금만 하심",
        "unable": "농사나 밭일이 어려움",
    }
    add_note(notes, farm_notes.get(farm_work_status))

    if payload.get("dizziness_present") is True:
        add_note(notes, "어지럼 있다고 하심")
    if payload.get("fall_present") is True:
        add_note(notes, "넘어지셨다고 하심")
    if payload.get("needs_family_followup"):
        add_note(notes, "가족 확인 필요")
    return "; ".join(notes) if notes else None


def has_signal_data(payload: dict[str, Any]) -> bool:
    tracked_keys = (
        "pain_present",
        "pain_locations",
        "pain_severity",
        "meal_status",
        "sleep_status",
        "hearing_aid_status",
        "activity_status",
        "farm_work_status",
        "dizziness_present",
        "fall_present",
        "needs_family_followup",
        "family_followup_reason",
        "note_summary",
    )
    for key in tracked_keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        if isinstance(value, bool):
            return True
        if value:
            return True
    return False


def build_health_signal(
    user_text: Optional[str],
    assistant_text: Optional[str],
    observed_at: datetime,
) -> Optional[dict[str, Any]]:
    normalized_user = normalize_text(user_text)
    normalized_assistant = normalize_text(assistant_text)
    if not normalized_user and not normalized_assistant:
        return None

    source_text = normalized_user or ""
    assistant_flags = extract_turn_flags(normalized_assistant)

    pain_present = detect_boolean_signal(
        source_text,
        PAIN_POSITIVE_PATTERNS,
        PAIN_NEGATIVE_PATTERNS,
    )
    pain_locations = detect_pain_locations(source_text) if pain_present is True else None
    pain_severity = detect_pain_severity(source_text) if pain_present is True else None
    meal_status = detect_meal_status(source_text)
    sleep_status = detect_sleep_status(source_text)
    hearing_aid_status = detect_hearing_aid_status(source_text)
    activity_status = detect_activity_status(source_text)
    farm_work_status = detect_farm_work_status(source_text)
    dizziness_present = detect_boolean_signal(
        source_text,
        DIZZINESS_POSITIVE_PATTERNS,
        DIZZINESS_NEGATIVE_PATTERNS,
    )
    fall_present = detect_boolean_signal(
        source_text,
        FALL_POSITIVE_PATTERNS,
        FALL_NEGATIVE_PATTERNS,
    )

    needs_family_followup = False
    risk_level = "normal"
    followup_reasons: list[str] = []

    if assistant_flags["family_call_prompted"]:
        needs_family_followup = True
        risk_level = "urgent"
        followup_reasons.append("assistant_prompted_family_call")

    if fall_present is True:
        needs_family_followup = True
        risk_level = "urgent"
        followup_reasons.append("fall_mentioned")

    if dizziness_present is True and risk_level != "urgent":
        risk_level = "watch"
        followup_reasons.append("dizziness_mentioned")

    if pain_present is True and pain_severity == "severe" and risk_level == "normal":
        risk_level = "watch"
        followup_reasons.append("severe_pain")

    if meal_status in {"poor", "skipped"} and risk_level == "normal":
        risk_level = "watch"
        followup_reasons.append("poor_meal")

    if activity_status == "unable" and risk_level == "normal":
        risk_level = "watch"
        followup_reasons.append("unable_to_move")

    if risk_level == "watch" and (
        fall_present is True or activity_status == "unable" or meal_status == "skipped"
    ):
        needs_family_followup = True

    family_followup_reason = ", ".join(dict.fromkeys(followup_reasons)) or None

    payload = {
        "signal_date": to_signal_date(observed_at),
        "observed_at": to_isoformat(observed_at),
        "extraction_method": "rule_based",
        "extraction_version": SIGNAL_EXTRACTION_VERSION,
        "review_status": "auto",
        "pain_present": pain_present,
        "pain_locations": pain_locations,
        "pain_severity": pain_severity,
        "meal_status": meal_status,
        "sleep_status": sleep_status,
        "hearing_aid_status": hearing_aid_status,
        "activity_status": activity_status,
        "farm_work_status": farm_work_status,
        "dizziness_present": dizziness_present,
        "fall_present": fall_present,
        "needs_family_followup": needs_family_followup,
        "risk_level": risk_level,
        "family_followup_reason": family_followup_reason,
        "evidence": {
            "user_transcript": normalized_user,
            "assistant_transcript": normalized_assistant,
            "assistant_flags": assistant_flags,
        },
    }
    payload["note_summary"] = build_note_summary(payload)
    if not has_signal_data(payload):
        return None
    return payload


class SupabaseRestClient:
    def __init__(self, base_url: str, service_role_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_role_key = service_role_key

    def request_json(
        self,
        method: str,
        table: str,
        *,
        query: Optional[dict[str, str]] = None,
        payload: Optional[Any] = None,
        prefer: Optional[str] = None,
    ) -> Any:
        query_string = ""
        if query:
            query_string = "?" + urllib_parse.urlencode(query, safe=",()")
        url = f"{self.base_url}/rest/v1/{table}{query_string}"
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if prefer:
            headers["Prefer"] = prefer

        request = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            category, message = parse_supabase_error_category(
                status_code=exc.code,
                table=table,
                error_body=error_body,
            )
            raise SupabaseStorageError(
                message,
                category=category,
                table=table,
                status_code=exc.code,
                raw_body=error_body,
            ) from exc
        except urllib_error.URLError as exc:
            raise SupabaseStorageError(
                f"Supabase request failed: {exc.reason}",
                category="network",
                table=table,
            ) from exc

        if not raw_body:
            return None
        return json.loads(raw_body)

    def select(
        self,
        table: str,
        *,
        query: Optional[dict[str, str]] = None,
    ) -> Any:
        return self.request_json("GET", table, query=query)

    def insert(self, table: str, payload: Any) -> Any:
        return self.request_json(
            "POST",
            table,
            payload=payload,
            prefer="return=representation",
        )

    def upsert(self, table: str, payload: Any, on_conflict: str) -> Any:
        query = {"on_conflict": on_conflict}
        return self.request_json(
            "POST",
            table,
            query=query,
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )

    def update(self, table: str, payload: Any, *, query: dict[str, str]) -> Any:
        return self.request_json(
            "PATCH",
            table,
            query=query,
            payload=payload,
            prefer="return=representation",
        )


@dataclass
class ConversationStore:
    conversation_key: str
    external_client_id: str
    resumed: bool
    model_name: str
    voice_name: str
    prompt_version: str = PROMPT_VERSION
    prompt_profile: dict[str, Any] = field(default_factory=merge_prompt_profile)
    enabled: bool = field(default_factory=has_supabase_storage)
    client: Optional[SupabaseRestClient] = None
    family_id: Optional[str] = None
    care_recipient_id: Optional[str] = None
    device_installation_id: Optional[str] = None
    session_id: Optional[str] = None
    connection_id: Optional[str] = None
    turn_index: int = 0
    session_closed: bool = False
    connection_close_reason: Optional[str] = None
    connection_error_message: Optional[str] = None
    disabled_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        self.client = SupabaseRestClient(
            os.getenv("SUPABASE_URL", "").strip(),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        )

    async def initialize(self) -> None:
        if not self.enabled or not self.client:
            return
        try:
            await asyncio.to_thread(self._initialize_sync)
        except SupabaseStorageError as exc:
            self.enabled = False
            self.disabled_reason = self._build_disabled_reason(exc)
            if exc.category == "missing_schema":
                logger.warning("Supabase 저장 비활성화: %s", self.disabled_reason)
            else:
                logger.exception("Supabase 저장 초기화 실패")
                if not self.disabled_reason:
                    self.disabled_reason = str(exc)
        except Exception as exc:
            self.enabled = False
            self.disabled_reason = str(exc)
            logger.exception("Supabase 저장 초기화 실패")

    def get_status(self) -> dict[str, Any]:
        return {
            "configured": has_supabase_storage(),
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
        }

    def _build_disabled_reason(self, exc: SupabaseStorageError) -> str:
        if exc.category == "missing_schema":
            return (
                f"Supabase table '{exc.table}' is missing. "
                "Apply supabase/migrations/20260327090000_initial_schema.sql."
            )
        return str(exc)

    async def update_resumption_handle(self, handle: str) -> None:
        if not self.enabled or not self.client or not self.session_id or not self.connection_id:
            return
        if not handle:
            return
        try:
            await asyncio.to_thread(self._update_resumption_handle_sync, handle)
        except Exception:
            logger.exception("세션 복구 핸들 저장 실패")

    async def record_turn(
        self,
        *,
        started_at: datetime,
        completed_at: datetime,
        user_transcript: Optional[str],
        assistant_transcript: Optional[str],
    ) -> None:
        if not self.enabled or not self.client or not self.session_id or not self.care_recipient_id:
            return

        normalized_user = normalize_text(user_transcript)
        normalized_assistant = normalize_text(assistant_transcript)
        assistant_flags = extract_turn_flags(normalized_assistant)

        turn_status = "complete"
        if not normalized_user and not normalized_assistant:
            turn_status = "discarded"

        user_transcript_status = "captured"
        if not normalized_user:
            user_transcript_status = "empty"
        elif assistant_flags["needs_repeat_prompt"]:
            user_transcript_status = "unclear"

        assistant_transcript_status = "captured" if normalized_assistant else "empty"

        self.turn_index += 1
        turn_index = self.turn_index

        turn_payload = {
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "care_recipient_id": self.care_recipient_id,
            "turn_index": turn_index,
            "turn_status": turn_status,
            "started_at": to_isoformat(started_at),
            "completed_at": to_isoformat(completed_at),
            "user_transcript": normalized_user,
            "assistant_transcript": normalized_assistant,
            "user_transcript_status": user_transcript_status,
            "assistant_transcript_status": assistant_transcript_status,
            "needs_repeat_prompt": assistant_flags["needs_repeat_prompt"],
            "hearing_aid_prompted": assistant_flags["hearing_aid_prompted"],
            "family_call_prompted": assistant_flags["family_call_prompted"],
            "raw_turn": {
                "conversation_key": self.conversation_key,
                "external_client_id": self.external_client_id,
                "assistant_flags": assistant_flags,
                "prompt_version": self.prompt_version,
            },
        }

        signal_payload = build_health_signal(normalized_user, normalized_assistant, completed_at)

        try:
            await asyncio.to_thread(
                self._record_turn_sync,
                turn_payload,
                signal_payload,
            )
        except Exception:
            logger.exception("대화 턴 저장 실패")

    async def complete_session(self, *, ended_reason: str, status: str) -> None:
        if self.session_closed or not self.enabled or not self.client or not self.session_id:
            return
        self.session_closed = True
        self.connection_close_reason = ended_reason
        try:
            await asyncio.to_thread(self._complete_session_sync, ended_reason, status)
        except Exception:
            logger.exception("대화 세션 종료 저장 실패")

    async def fail_session(self, message: str) -> None:
        self.connection_close_reason = self.connection_close_reason or "bridge_error"
        self.connection_error_message = message
        if not self.enabled or not self.client or not self.session_id:
            return
        try:
            await asyncio.to_thread(self._fail_session_sync, message)
        except Exception:
            logger.exception("대화 세션 오류 상태 저장 실패")

    async def close_connection(self) -> None:
        if not self.enabled or not self.client or not self.connection_id:
            return
        try:
            await asyncio.to_thread(self._close_connection_sync)
        except Exception:
            logger.exception("웹소켓 연결 종료 저장 실패")

    def _initialize_sync(self) -> None:
        if not self.client:
            return
        family_row = self._upsert_family()
        self.family_id = family_row["id"]

        recipient_row = self._upsert_care_recipient(self.family_id)
        self.care_recipient_id = recipient_row["id"]
        self.prompt_profile = merge_prompt_profile(recipient_row.get("prompt_profile"))

        device_row = self._upsert_device_installation(self.care_recipient_id)
        self.device_installation_id = device_row["id"]

        session_row = self._get_or_create_session()
        self.session_id = session_row["id"]

        connection_row = self._create_connection()
        self.connection_id = connection_row["id"]
        self.turn_index = self._fetch_last_turn_index()

    def _upsert_family(self) -> dict[str, Any]:
        payload = [
            {
                "external_key": DEFAULT_FAMILY_EXTERNAL_KEY,
                "family_name": DEFAULT_FAMILY_NAME,
                "timezone": resolve_timezone_name(),
            }
        ]
        rows = self.client.upsert("families", payload, "external_key")
        return rows[0]

    def _upsert_care_recipient(self, family_id: str) -> dict[str, Any]:
        default_profile = merge_prompt_profile()
        existing_rows = self.client.select(
            "care_recipients",
            query={
                "external_key": f"eq.{DEFAULT_CARE_RECIPIENT_EXTERNAL_KEY}",
                "select": "id,prompt_profile",
                "limit": "1",
            },
        )
        if existing_rows:
            care_recipient_id = existing_rows[0]["id"]
            merged_prompt_profile = merge_prompt_profile(existing_rows[0].get("prompt_profile"))
            updated_rows = self.client.update(
                "care_recipients",
                {
                    "family_id": family_id,
                    "full_name": DEFAULT_CARE_RECIPIENT_FULL_NAME,
                    "display_name": DEFAULT_CARE_RECIPIENT_DISPLAY_NAME,
                    "prompt_profile": merged_prompt_profile,
                    "active": True,
                },
                query={
                    "id": f"eq.{care_recipient_id}",
                    "select": "id,prompt_profile",
                },
            )
            return updated_rows[0]

        payload = [
            {
                "external_key": DEFAULT_CARE_RECIPIENT_EXTERNAL_KEY,
                "family_id": family_id,
                "full_name": DEFAULT_CARE_RECIPIENT_FULL_NAME,
                "display_name": DEFAULT_CARE_RECIPIENT_DISPLAY_NAME,
                "prompt_profile": default_profile,
            }
        ]
        try:
            rows = self.client.insert("care_recipients", payload)
            return rows[0]
        except RuntimeError:
            fallback_rows = self.client.select(
                "care_recipients",
                query={
                    "external_key": f"eq.{DEFAULT_CARE_RECIPIENT_EXTERNAL_KEY}",
                    "select": "id,prompt_profile",
                    "limit": "1",
                },
            )
            if not fallback_rows:
                raise

            care_recipient_id = fallback_rows[0]["id"]
            merged_prompt_profile = merge_prompt_profile(fallback_rows[0].get("prompt_profile"))
            updated_rows = self.client.update(
                "care_recipients",
                {
                    "family_id": family_id,
                    "full_name": DEFAULT_CARE_RECIPIENT_FULL_NAME,
                    "display_name": DEFAULT_CARE_RECIPIENT_DISPLAY_NAME,
                    "prompt_profile": merged_prompt_profile,
                    "active": True,
                },
                query={
                    "id": f"eq.{care_recipient_id}",
                    "select": "id,prompt_profile",
                },
            )
            return updated_rows[0]

    def _upsert_device_installation(self, care_recipient_id: str) -> dict[str, Any]:
        payload = [
            {
                "care_recipient_id": care_recipient_id,
                "client_id": self.external_client_id,
                "platform": "web_pwa",
                "last_seen_at": to_isoformat(now_utc()),
                "metadata": {
                    "conversation_key": self.conversation_key,
                },
            }
        ]
        rows = self.client.upsert("device_installations", payload, "client_id")
        return rows[0]

    def _get_or_create_session(self) -> dict[str, Any]:
        rows = self.client.select(
            "conversation_sessions",
            query={
                "conversation_key": f"eq.{self.conversation_key}",
                "select": "id,status",
                "limit": "1",
            },
        )
        if rows:
            session_id = rows[0]["id"]
            updated = self.client.update(
                "conversation_sessions",
                {
                    "device_installation_id": self.device_installation_id,
                    "external_client_id": self.external_client_id,
                    "status": "active",
                    "model_name": self.model_name,
                    "voice_name": self.voice_name,
                    "metadata": {
                        "last_resumed": self.resumed,
                        "prompt_version": self.prompt_version,
                        "prompt_profile": self.prompt_profile,
                    },
                },
                query={
                    "id": f"eq.{session_id}",
                    "select": "id,status",
                },
            )
            return updated[0]

        payload = [
            {
                "care_recipient_id": self.care_recipient_id,
                "device_installation_id": self.device_installation_id,
                "conversation_key": self.conversation_key,
                "external_client_id": self.external_client_id,
                "source": "web_pwa",
                "transport": "gemini_live",
                "status": "active",
                "started_at": to_isoformat(now_utc()),
                "model_name": self.model_name,
                "voice_name": self.voice_name,
                "metadata": {
                    "resumed_on_open": self.resumed,
                    "prompt_version": self.prompt_version,
                    "prompt_profile": self.prompt_profile,
                },
            }
        ]
        rows = self.client.insert("conversation_sessions", payload)
        return rows[0]

    def _create_connection(self) -> dict[str, Any]:
        payload = [
            {
                "session_id": self.session_id,
                "external_client_id": self.external_client_id,
                "resumed": self.resumed,
                "opened_at": to_isoformat(now_utc()),
                "metadata": {
                    "conversation_key": self.conversation_key,
                    "prompt_version": self.prompt_version,
                },
            }
        ]
        rows = self.client.insert("session_connections", payload)
        return rows[0]

    def _fetch_last_turn_index(self) -> int:
        rows = self.client.select(
            "conversation_turns",
            query={
                "session_id": f"eq.{self.session_id}",
                "select": "turn_index",
                "order": "turn_index.desc",
                "limit": "1",
            },
        )
        if not rows:
            return 0
        return int(rows[0].get("turn_index") or 0)

    def _update_resumption_handle_sync(self, handle: str) -> None:
        self.client.update(
            "conversation_sessions",
            {"last_resumption_handle": handle},
            query={"id": f"eq.{self.session_id}"},
        )
        self.client.update(
            "session_connections",
            {"gemini_resumption_handle": handle},
            query={"id": f"eq.{self.connection_id}"},
        )

    def _record_turn_sync(
        self,
        turn_payload: dict[str, Any],
        signal_payload: Optional[dict[str, Any]],
    ) -> None:
        rows = self.client.insert("conversation_turns", [turn_payload])
        turn_id = rows[0]["id"]

        if signal_payload:
            signal_payload = {
                **signal_payload,
                "turn_id": turn_id,
                "session_id": self.session_id,
                "care_recipient_id": self.care_recipient_id,
            }
            self.client.upsert("turn_health_signals", [signal_payload], "turn_id")

        self.client.update(
            "device_installations",
            {"last_seen_at": to_isoformat(now_utc())},
            query={"id": f"eq.{self.device_installation_id}"},
        )

    def _complete_session_sync(self, ended_reason: str, status: str) -> None:
        self.client.update(
            "conversation_sessions",
            {
                "status": status,
                "ended_reason": ended_reason,
                "ended_at": to_isoformat(now_utc()),
            },
            query={"id": f"eq.{self.session_id}"},
        )

    def _fail_session_sync(self, message: str) -> None:
        self.client.update(
            "conversation_sessions",
            {
                "status": "error",
                "ended_reason": "bridge_error",
                "ended_at": to_isoformat(now_utc()),
                "metadata": {
                    "last_error": message,
                },
            },
            query={"id": f"eq.{self.session_id}"},
        )

    def _close_connection_sync(self) -> None:
        payload = {
            "closed_at": to_isoformat(now_utc()),
            "close_reason": self.connection_close_reason,
            "error_message": self.connection_error_message,
        }
        self.client.update(
            "session_connections",
            payload,
            query={"id": f"eq.{self.connection_id}"},
        )
