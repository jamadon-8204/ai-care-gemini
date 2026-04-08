"""
가준이 v2 — Supabase 저장 모듈
MVP 3테이블: users / conversations / utterances
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger("gajuni.storage")

# ---------------------------------------------------------------------------
# 환경변수
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
TIMEZONE_NAME = os.getenv("TZ", "Asia/Seoul").strip()

# 어머니 고정 user_id (MVP 단계 — 사용자 1명)
MOTHER_USER_ID = os.getenv("MOTHER_USER_ID", "").strip()

# 백업 로그 디렉터리
BACKUP_DIR = Path(os.getenv("BACKUP_LOG_DIR", "/tmp/gajuni_backup"))


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def resolve_timezone_name() -> str:
    return TIMEZONE_NAME


def has_supabase_storage() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _get_supabase_client():
    """supabase-py 클라이언트 반환. 환경변수 없으면 None."""
    if not has_supabase_storage():
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:
        logger.error("Supabase 클라이언트 생성 실패: %s", exc)
        return None


def _backup_write(event: str, payload: dict) -> None:
    """Supabase 실패 시 로컬 JSON 백업."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        backup_file = BACKUP_DIR / f"backup_{date_str}.jsonl"
        line = json.dumps({"event": event, "ts": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False)
        with backup_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        logger.error("백업 쓰기 실패: %s", exc)


# ---------------------------------------------------------------------------
# ConversationStore
# ---------------------------------------------------------------------------

class ConversationStore:
    """
    WebSocket 세션 1개당 1인스턴스.
    server.py의 websocket_bridge()에서 생성되고,
    record_turn()으로 발화를 1턴마다 즉시 저장한다.
    """

    def __init__(
        self,
        conversation_key: str,
        external_client_id: str,
        resumed: bool,
        model_name: str,
        voice_name: str,
    ) -> None:
        self.conversation_key = conversation_key
        self.external_client_id = external_client_id
        self.resumed = resumed
        self.model_name = model_name
        self.voice_name = voice_name

        self._supabase = _get_supabase_client()
        self._conversation_id: Optional[str] = None
        self._user_id: Optional[str] = MOTHER_USER_ID or None

        self.connection_close_reason: Optional[str] = None
        self.connection_error_message: Optional[str] = None

        # server.py가 참조하는 prompt_profile
        self.prompt_profile: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """세션 시작 시 conversations 레코드 생성."""
        if not self._supabase:
            logger.warning("Supabase 미연결 — 메모리 전용 모드로 실행")
            self._conversation_id = str(uuid4())
            self._load_prompt_profile_fallback()
            return

        try:
            # 사용자 확인 / 자동 생성
            self._user_id = await self._ensure_user()

            # conversations 레코드 삽입
            row = {
                "id": str(uuid4()),
                "user_id": self._user_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "trigger_type": "resume" if self.resumed else "new",
                "metadata": {
                    "client_id": self.external_client_id,
                    "conversation_key": self.conversation_key,
                    "model": self.model_name,
                    "voice": self.voice_name,
                },
            }
            result = self._supabase.table("conversations").insert(row).execute()
            self._conversation_id = result.data[0]["id"]
            logger.info("대화 세션 생성: conversation_id=%s user_id=%s", self._conversation_id, self._user_id)

            # prompt_profile 로드 (users.metadata 활용)
            await self._load_prompt_profile()

        except Exception as exc:
            logger.error("initialize 실패: %s", exc)
            _backup_write("initialize_error", {"error": str(exc), "conversation_key": self.conversation_key})
            self._conversation_id = str(uuid4())
            self._load_prompt_profile_fallback()

    async def _ensure_user(self) -> str:
        """MOTHER_USER_ID 있으면 그대로 사용, 없으면 어머니 레코드 조회/생성."""
        if self._user_id:
            return self._user_id

        # 이름으로 조회
        result = self._supabase.table("users").select("id").eq("name", "표순선").execute()
        if result.data:
            uid = result.data[0]["id"]
            logger.info("어머니 레코드 조회: user_id=%s", uid)
            return uid

        # 없으면 생성
        row = {
            "id": str(uuid4()),
            "name": "표순선",
            "nickname": "할머니",
            "birth_year": 1956,
            "metadata": {},
        }
        result = self._supabase.table("users").insert(row).execute()
        uid = result.data[0]["id"]
        logger.info("어머니 레코드 생성: user_id=%s", uid)
        return uid

    async def _load_prompt_profile(self) -> None:
        """users.metadata에서 prompt_profile 로드."""
        try:
            result = self._supabase.table("users").select("metadata, nickname, birth_year").eq("id", self._user_id).execute()
            if result.data:
                row = result.data[0]
                self.prompt_profile = {
                    "nickname": row.get("nickname", "할머니"),
                    "birth_year": row.get("birth_year", 1956),
                    **(row.get("metadata") or {}),
                }
        except Exception as exc:
            logger.warning("prompt_profile 로드 실패: %s", exc)
            self._load_prompt_profile_fallback()

    def _load_prompt_profile_fallback(self) -> None:
        self.prompt_profile = {"nickname": "할머니", "birth_year": 1956}

    # ------------------------------------------------------------------
    # 발화 저장 (1턴마다 즉시)
    # ------------------------------------------------------------------

    async def record_turn(
        self,
        started_at: datetime,
        completed_at: datetime,
        user_transcript: Optional[str],
        assistant_transcript: Optional[str],
    ) -> None:
        """turn_complete 이벤트마다 호출. user + assistant 발화 각각 저장."""

        if not user_transcript and not assistant_transcript:
            return

        payload = {
            "conversation_id": self._conversation_id,
            "user_id": self._user_id,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "user_transcript": user_transcript,
            "assistant_transcript": assistant_transcript,
        }

        if not self._supabase:
            _backup_write("record_turn", payload)
            logger.info("백업 저장(Supabase 없음): user=%s assistant=%s", user_transcript, assistant_transcript)
            return

        rows = []
        if user_transcript:
            rows.append({
                "id": str(uuid4()),
                "conversation_id": self._conversation_id,
                "user_id": self._user_id,
                "speaker": "user",
                "content": user_transcript,
                "spoken_at": started_at.isoformat(),
                "raw_payload": {"turn_completed_at": completed_at.isoformat()},
            })
        if assistant_transcript:
            rows.append({
                "id": str(uuid4()),
                "conversation_id": self._conversation_id,
                "user_id": self._user_id,
                "speaker": "assistant",
                "content": assistant_transcript,
                "spoken_at": completed_at.isoformat(),
                "raw_payload": {},
            })

        try:
            self._supabase.table("utterances").insert(rows).execute()
            logger.info(
                "발화 저장 완료: conversation_id=%s user=%s assistant=%s",
                self._conversation_id,
                user_transcript,
                assistant_transcript,
            )
        except Exception as exc:
            logger.error("utterances 저장 실패: %s", exc)
            _backup_write("record_turn_error", {**payload, "error": str(exc)})

    # ------------------------------------------------------------------
    # 세션 종료
    # ------------------------------------------------------------------

    async def complete_session(self, ended_reason: str = "completed", status: str = "completed") -> None:
        if not self._supabase or not self._conversation_id:
            return
        try:
            now = datetime.now(timezone.utc)
            self._supabase.table("conversations").update({
                "ended_at": now.isoformat(),
                "metadata": {
                    "ended_reason": ended_reason,
                    "status": status,
                    "close_reason": self.connection_close_reason,
                },
            }).eq("id", self._conversation_id).execute()
            logger.info("대화 세션 종료: conversation_id=%s reason=%s", self._conversation_id, ended_reason)
        except Exception as exc:
            logger.error("complete_session 실패: %s", exc)

    async def fail_session(self, error_message: str) -> None:
        await self.complete_session(ended_reason="error", status="failed")

    async def close_connection(self) -> None:
        reason = self.connection_close_reason or "unknown"
        status = "failed" if self.connection_error_message else "completed"
        await self.complete_session(ended_reason=reason, status=status)

    async def update_resumption_handle(self, handle: str) -> None:
        if not self._supabase or not self._conversation_id:
            return
        try:
            self._supabase.table("conversations").update({
                "metadata": {"resumption_handle": handle},
            }).eq("id", self._conversation_id).execute()
        except Exception as exc:
            logger.warning("resumption_handle 업데이트 실패: %s", exc)
