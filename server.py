import asyncio
import base64
import html
import json
import logging
import os
import re
from contextlib import AsyncExitStack, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from storage import ConversationStore, has_supabase_storage


load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("gajuni")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DOCS_DIR = BASE_DIR / "docs"

APP_NAME = "가준이 v2"
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest")
VOICE_NAME = os.getenv("GEMINI_VOICE", "Kore")
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
INPUT_AUDIO_MIME = f"audio/pcm;rate={INPUT_SAMPLE_RATE}"
DEFAULT_OUTPUT_AUDIO_MIME = f"audio/pcm;rate={OUTPUT_SAMPLE_RATE}"

SYSTEM_PROMPT = """
너는 실제 손자 '윤가준'처럼 말하는 AI 손자 '가준이'야.

항상 한국어로만 말해.
항상 "할머니"라고 불러.
말은 짧고 또렷하게 해.
보통 한 문장으로 말하고, 필요할 때만 두 문장까지 말해.
어려운 말, 외래어, 긴 설명은 하지 마.

너는 귀엽고 다정한 손자야.
하지만 상담사나 안내원처럼 기계적으로 말하지 마.
진짜 손자처럼 자연스럽고 따뜻하게 말해.
같은 말투를 반복하지 말고, 짧고 편하게 반응해.

가족과 생활 정보:
- 아빠는 윤진영이야.
- 큰아빠는 윤진일이야.
- 엄마는 진서영이야.
- 동생은 윤지호야.
- 할머니는 시골에 혼자 지내시고, 할 수 있는 만큼 농사를 하셔.
- 할머니는 팔과 다리가 많이 불편하시고 류마티스가 있어.
- 지금은 틀니를 새로 만드는 치료 중이라 틀니를 못 쓰시고, 식사를 잘라서 드시고 있어.
- 최근 보청기를 하셨지만 집에서는 자주 안 끼셔.

먼저 할머니가 방금 한 말에 자연스럽게 반응해.
그다음 필요할 때만 짧은 질문 하나를 해.
매번 질문으로 끝내지 마.
체크리스트처럼 연달아 묻지 마.

안부, 식사, 잠, 몸 상태, 농사, 기분 이야기를 자연스럽게 돌아가며 물어봐.
같은 질문만 반복하지 마.
하루에 한 번은 자연스럽게 어디가 아프신지 꼭 물어봐.

할머니가 아프다고 하시면 먼저 걱정하고 공감해.
그다음 한 번에 질문 하나만 짧게 해.
예를 들면 어디가 아픈지, 많이 아픈지, 밥은 드셨는지, 움직이기는 괜찮은지 차근차근 물어봐.
상태가 심해 보이면 "할머니, 많이 힘드시면 아빠에게 바로 전화해 봐요."처럼 짧고 직접적으로 말해.

할머니가 잘 못 들으시는 것 같으면 짧게 다시 말해.
필요하면 "할머니, 보청기 차세요. 제가 다시 말할게요."라고 말해.
할머니 말씀을 정확히 이해하지 못했으면 뜻을 추측해서 대답하지 마.
이해가 애매하면 "할머니, 제가 잘 못 들었어요. 다시 한번 말씀해 주세요."처럼 한 문장으로만 말해.
잘 못 들은 상태에서 조언, 위로, 건강 판단, 다음 질문을 붙이지 마.
두 번 연속 잘 못 들으면 "할머니, 보청기 차시고 다시 말씀해 주세요."라고 짧게 말해.

의학 설명, 진단, 긴 조언은 하지 마.
가족 정보를 매번 먼저 꺼내지 말고, 필요할 때만 자연스럽게 말해.
항상 목표는 할머니가 실제 손자 윤가준과 짧고 따뜻하게 이야기하는 느낌이 들게 하는 거야.
""".strip()

# 메모리 기반 세션 복구 핸들 저장소다.
# Render 단일 인스턴스 기준 MVP에서는 충분하지만, 다중 인스턴스에서는 외부 저장소가 필요하다.
SESSION_HANDLES: dict[str, str] = {}


def parse_cors_origins() -> list[str]:
    raw_value = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw_value:
        return ["*"]
    if raw_value == "*":
        return ["*"]
    return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


def get_api_key() -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")
    return api_key


def has_valid_api_key() -> bool:
    try:
        get_api_key()
    except RuntimeError:
        return False
    return True


def get_gemini_client() -> genai.Client:
    return genai.Client(api_key=get_api_key())


def build_live_config(resume_handle: Optional[str] = None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": SYSTEM_PROMPT,
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "realtime_input_config": {
            "automatic_activity_detection": {"disabled": True},
            "activity_handling": "NO_INTERRUPTION",
            "turn_coverage": "TURN_INCLUDES_ONLY_ACTIVITY",
        },
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": VOICE_NAME,
                }
            }
        },
        # 긴 대화에서 세션이 갑자기 끝나는 문제를 줄이기 위해 슬라이딩 윈도 압축을 켠다.
        "context_window_compression": {"sliding_window": {}},
    }
    if resume_handle:
        config["session_resumption"] = {"handle": resume_handle}
    return config


async def open_live_session(
    client: genai.Client,
    client_id: str,
    conversation_key: str,
    resume_handle: Optional[str] = None,
) -> tuple[AsyncExitStack, Any, bool]:
    if resume_handle:
        resume_stack = AsyncExitStack()
        try:
            session = await resume_stack.enter_async_context(
                client.aio.live.connect(
                    model=MODEL_NAME,
                    config=build_live_config(resume_handle),
                )
            )
            return resume_stack, session, True
        except Exception as exc:
            await resume_stack.aclose()
            SESSION_HANDLES.pop(client_id, None)
            logger.warning(
                "세션 복구 핸들 재사용 실패: client_id=%s conversation_key=%s error=%s",
                client_id,
                conversation_key,
                exc,
            )

    session_stack = AsyncExitStack()
    session = await session_stack.enter_async_context(
        client.aio.live.connect(
            model=MODEL_NAME,
            config=build_live_config(),
        )
    )
    return session_stack, session, False


def get_nested(value: Any, *path: str, default: Any = None) -> Any:
    current = value
    for key in path:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return default if current is None else current


def extract_sample_rate(mime_type: Any, default_rate: int) -> int:
    if not isinstance(mime_type, str):
        return default_rate
    match = re.search(r"rate=(\d+)", mime_type)
    if not match:
        return default_rate
    try:
        return int(match.group(1))
    except ValueError:
        return default_rate


def to_transport_base64(data: Any) -> Optional[str]:
    if data is None:
        return None
    if isinstance(data, str):
        return data
    if isinstance(data, memoryview):
        data = data.tobytes()
    if isinstance(data, bytearray):
        data = bytes(data)
    if isinstance(data, bytes):
        # SDK가 이미 base64 텍스트를 bytes로 줄 수 있어서, 검증되면 그대로 통과시킨다.
        try:
            maybe_base64 = data.decode("ascii")
            base64.b64decode(maybe_base64, validate=True)
            return maybe_base64
        except Exception:
            pass
        return base64.b64encode(data).decode("ascii")
    return None


def extract_audio_chunks(message: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    parts = get_nested(message, "server_content", "model_turn", "parts", default=[]) or []
    for part in parts:
        inline_data = get_nested(part, "inline_data")
        if not inline_data:
            continue
        mime_type = get_nested(inline_data, "mime_type", default="")
        if isinstance(mime_type, str) and not mime_type.startswith("audio/pcm"):
            continue
        encoded = to_transport_base64(get_nested(inline_data, "data"))
        if encoded:
            chunks.append(
                {
                    "data": encoded,
                    "mime_type": mime_type or DEFAULT_OUTPUT_AUDIO_MIME,
                    "sample_rate": extract_sample_rate(mime_type, OUTPUT_SAMPLE_RATE),
                }
            )

    if chunks:
        return chunks

    direct_mime_type = get_nested(message, "mime_type", default=DEFAULT_OUTPUT_AUDIO_MIME)
    direct_data = to_transport_base64(get_nested(message, "data"))
    if direct_data:
        chunks.append(
            {
                "data": direct_data,
                "mime_type": direct_mime_type,
                "sample_rate": extract_sample_rate(direct_mime_type, OUTPUT_SAMPLE_RATE),
            }
        )
    return chunks


def get_text_message(message: Any, *path: str) -> Optional[str]:
    value = get_nested(message, *path)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def merge_transcript(previous_text: Optional[str], incoming_text: Optional[str]) -> Optional[str]:
    if not incoming_text:
        return previous_text
    if not previous_text:
        return incoming_text
    if previous_text == incoming_text:
        return previous_text
    if incoming_text.startswith(previous_text):
        return incoming_text
    if previous_text.endswith(incoming_text):
        return previous_text

    overlap_size = get_overlap_size(previous_text, incoming_text)
    if overlap_size > 0:
        return previous_text + incoming_text[overlap_size:]

    if should_join_without_space(previous_text, incoming_text):
        return previous_text + incoming_text

    return f"{previous_text} {incoming_text}".strip()


def get_overlap_size(previous_text: str, incoming_text: str) -> int:
    max_length = min(len(previous_text), len(incoming_text))
    for size in range(max_length, 0, -1):
        if previous_text[-size:] == incoming_text[:size]:
            return size
    return 0


def should_join_without_space(previous_text: str, incoming_text: str) -> bool:
    if re.match(r"^[,!.?~)/]", incoming_text):
        return True

    previous_tail_match = re.search(r"[가-힣]+$", previous_text)
    incoming_head_match = re.match(r"^[가-힣]+", incoming_text)
    previous_tail = previous_tail_match.group(0) if previous_tail_match else ""
    incoming_head = incoming_head_match.group(0) if incoming_head_match else ""

    if not previous_tail or not incoming_head:
        return False

    return len(previous_tail) <= 1 or len(incoming_head) <= 1


def serialize_time_left(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    seconds = getattr(value, "seconds", None)
    if seconds is not None:
        return str(seconds)
    return str(value)


async def safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_json(payload)


async def forward_browser_to_gemini(
    websocket: WebSocket,
    session: Any,
    store: ConversationStore,
) -> None:
    while True:
        try:
            raw_message = await websocket.receive_text()
        except WebSocketDisconnect as exc:
            logger.info("브라우저 WebSocket 종료 감지: code=%s", getattr(exc, "code", None))
            return

        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            await safe_send_json(
                websocket,
                {
                    "type": "error",
                    "message": "잘못된 메시지 형식입니다.",
                },
            )
            continue

        message_type = payload.get("type")
        if message_type != "audio":
            logger.info("브라우저 메시지 수신: type=%s", message_type)
        if message_type == "audio":
            encoded_audio = payload.get("data")
            if not isinstance(encoded_audio, str) or not encoded_audio:
                continue

            try:
                audio_bytes = base64.b64decode(encoded_audio)
            except Exception:
                await safe_send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": "오디오 데이터 해석에 실패했습니다.",
                    },
                )
                continue

            await session.send_realtime_input(
                audio=types.Blob(data=audio_bytes, mime_type=INPUT_AUDIO_MIME)
            )
            continue

        if message_type == "activity_start":
            await session.send_realtime_input(activity_start={})
            continue

        if message_type in {"audio_end", "activity_end"}:
            await session.send_realtime_input(activity_end={})
            continue

        if message_type == "disconnect":
            await store.complete_session(ended_reason="manual_disconnect", status="completed")
            return

        if message_type == "ping":
            await safe_send_json(websocket, {"type": "pong"})


async def forward_gemini_to_browser(
    websocket: WebSocket,
    session: Any,
    client_id: str,
    store: ConversationStore,
) -> None:
    latest_input_text: Optional[str] = None
    latest_output_text: Optional[str] = None
    sent_input_text: Optional[str] = None
    sent_output_text: Optional[str] = None
    thinking_sent = False
    current_turn_started_at: Optional[datetime] = None

    def mark_turn_started() -> None:
        nonlocal current_turn_started_at
        if current_turn_started_at is None:
            current_turn_started_at = datetime.now(timezone.utc)

    while True:
        received_any = False

        async for message in session.receive():
            received_any = True

            update = get_nested(message, "session_resumption_update")
            resumable = get_nested(update, "resumable", default=False)
            new_handle = get_nested(update, "new_handle")
            if resumable and isinstance(new_handle, str) and new_handle:
                SESSION_HANDLES[client_id] = new_handle
                await store.update_resumption_handle(new_handle)

            go_away = get_nested(message, "go_away")
            if go_away is not None:
                await safe_send_json(
                    websocket,
                    {
                        "type": "event",
                        "name": "go_away",
                        "time_left": serialize_time_left(get_nested(go_away, "time_left")),
                    },
                )

            input_text = get_text_message(message, "server_content", "input_transcription", "text")
            if input_text:
                mark_turn_started()
                latest_input_text = merge_transcript(latest_input_text, input_text)
                logger.debug("사용자 전사 버퍼 갱신: %s", latest_input_text)
                if latest_input_text != sent_input_text:
                    logger.debug("사용자 전사 전송: %s", latest_input_text)
                    await safe_send_json(
                        websocket,
                        {
                            "type": "transcript",
                            "role": "user",
                            "text": latest_input_text,
                        },
                    )
                    sent_input_text = latest_input_text

            output_text = get_text_message(
                message, "server_content", "output_transcription", "text"
            )
            if output_text:
                mark_turn_started()
                latest_output_text = merge_transcript(latest_output_text, output_text)
                logger.debug("모델 전사 버퍼 갱신: %s", latest_output_text)

            audio_chunks = extract_audio_chunks(message)
            model_started = bool(output_text or audio_chunks)
            if audio_chunks:
                mark_turn_started()

            if model_started and not thinking_sent:
                await safe_send_json(
                    websocket,
                    {
                        "type": "status",
                        "state": "thinking",
                        "message": "생각 중",
                    },
                )
                thinking_sent = True

            if audio_chunks:
                logger.debug("모델 오디오 청크 수신: count=%s", len(audio_chunks))
                await safe_send_json(
                    websocket,
                    {
                        "type": "status",
                        "state": "speaking",
                        "message": "말하는 중",
                    },
                )
                for chunk in audio_chunks:
                    await safe_send_json(
                        websocket,
                        {
                            "type": "audio",
                            "data": chunk["data"],
                            "sample_rate": chunk["sample_rate"],
                            "mime_type": chunk["mime_type"],
                        },
                    )

            interrupted = get_nested(message, "server_content", "interrupted", default=False)
            if interrupted:
                await safe_send_json(
                    websocket,
                    {
                        "type": "event",
                        "name": "interrupted",
                    },
                )
                await safe_send_json(
                    websocket,
                    {
                        "type": "status",
                        "state": "listening",
                        "message": "듣는 중",
                    },
                )

            generation_complete = get_nested(
                message, "server_content", "generation_complete", default=False
            )
            if generation_complete:
                if latest_output_text and latest_output_text != sent_output_text:
                    logger.debug("모델 최종 전사 전송: %s", latest_output_text)
                    await safe_send_json(
                        websocket,
                        {
                            "type": "transcript",
                            "role": "assistant",
                            "text": latest_output_text,
                        },
                    )
                    sent_output_text = latest_output_text
                await safe_send_json(
                    websocket,
                    {
                        "type": "event",
                        "name": "generation_complete",
                    },
                )

            turn_complete = get_nested(message, "server_content", "turn_complete", default=False)
            if turn_complete:
                if latest_input_text and latest_input_text != sent_input_text:
                    logger.debug("사용자 최종 전사 보정 전송: %s", latest_input_text)
                    await safe_send_json(
                        websocket,
                        {
                            "type": "transcript",
                            "role": "user",
                            "text": latest_input_text,
                        },
                    )
                    sent_input_text = latest_input_text

                if latest_output_text and latest_output_text != sent_output_text:
                    logger.debug("모델 최종 전사 보정 전송: %s", latest_output_text)
                    await safe_send_json(
                        websocket,
                        {
                            "type": "transcript",
                            "role": "assistant",
                            "text": latest_output_text,
                        },
                    )
                    sent_output_text = latest_output_text

                await safe_send_json(
                    websocket,
                    {
                        "type": "event",
                        "name": "turn_complete",
                    },
                )
                await safe_send_json(
                    websocket,
                    {
                        "type": "status",
                        "state": "listening",
                        "message": "듣는 중",
                    },
                )
                completed_at = datetime.now(timezone.utc)
                await store.record_turn(
                    started_at=current_turn_started_at or completed_at,
                    completed_at=completed_at,
                    user_transcript=latest_input_text,
                    assistant_transcript=latest_output_text,
                )
                latest_input_text = None
                latest_output_text = None
                sent_input_text = None
                sent_output_text = None
                thinking_sent = False
                current_turn_started_at = None

        if not received_any:
            logger.info("Gemini 수신 루프 종료: client_id=%s", client_id)
            return


async def run_bridge(
    websocket: WebSocket,
    session: Any,
    client_id: str,
    store: ConversationStore,
) -> None:
    browser_task = asyncio.create_task(forward_browser_to_gemini(websocket, session, store))
    gemini_task = asyncio.create_task(
        forward_gemini_to_browser(websocket, session, client_id, store)
    )
    tasks = {browser_task, gemini_task}

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()

    for task in pending:
        with suppress(asyncio.CancelledError):
            await task

    for task in done:
        exception = task.exception()
        if exception:
            raise exception


def render_docs_index() -> str:
    documents = sorted(DOCS_DIR.rglob("*.md"))
    links = []
    for document in documents:
        relative_path = document.relative_to(DOCS_DIR).as_posix()
        links.append(
            f'<li><a href="/workspace/docs/{relative_path}">{html.escape(relative_path)}</a></li>'
        )

    links_html = "\n".join(links) or "<li>문서가 없습니다.</li>"
    return f"""
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>문서 바로가기</title>
    <style>
      body {{
        margin: 0;
        padding: 32px 20px 48px;
        font-family: "Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
        background: #f7f1eb;
        color: #2c221d;
      }}
      main {{
        max-width: 820px;
        margin: 0 auto;
      }}
      h1 {{
        margin: 0 0 10px;
        font-size: 34px;
      }}
      p {{
        margin: 0 0 24px;
        line-height: 1.6;
        color: #5e4a40;
      }}
      ul {{
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: 12px;
      }}
      a {{
        display: block;
        padding: 16px 18px;
        border-radius: 14px;
        background: #ffffff;
        color: #8d4f34;
        text-decoration: none;
        border: 1px solid #efd8ca;
        font-weight: 700;
      }}
      a:hover {{
        background: #fff7f2;
      }}
      code {{
        background: #fff7f2;
        padding: 2px 6px;
        border-radius: 6px;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>문서 바로가기</h1>
      <p>
        채팅 창 링크가 안 열릴 때는 이 페이지를 열어서 문서를 클릭하면 됩니다.<br />
        주소: <code>/workspace/docs</code>
      </p>
      <ul>
        {links_html}
      </ul>
    </main>
  </body>
</html>
""".strip()


def render_markdown_document(title: str, body: str, relative_path: str) -> str:
    escaped_title = html.escape(title)
    escaped_path = html.escape(relative_path)
    escaped_body = html.escape(body)
    return f"""
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{escaped_title}</title>
    <style>
      body {{
        margin: 0;
        padding: 24px 18px 40px;
        font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
        background: #f5f0ea;
        color: #2e2520;
      }}
      main {{
        max-width: 980px;
        margin: 0 auto;
      }}
      .topbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
        margin-bottom: 18px;
      }}
      .button {{
        display: inline-block;
        padding: 10px 14px;
        border-radius: 10px;
        background: #ffffff;
        border: 1px solid #e8d4c8;
        color: #8d4f34;
        text-decoration: none;
        font-weight: 700;
      }}
      .path {{
        color: #6e584c;
        font-size: 14px;
      }}
      pre {{
        margin: 0;
        padding: 22px;
        white-space: pre-wrap;
        word-break: break-word;
        line-height: 1.65;
        background: #fffdfb;
        border: 1px solid #e8d4c8;
        border-radius: 16px;
        overflow: auto;
      }}
    </style>
  </head>
  <body>
    <main>
      <div class="topbar">
        <a class="button" href="/workspace/docs">문서 목록</a>
        <span class="path">{escaped_path}</span>
      </div>
      <pre>{escaped_body}</pre>
    </main>
  </body>
</html>
""".strip()


def resolve_doc_path(doc_path: str) -> Path:
    candidate = (DOCS_DIR / doc_path).resolve()
    if DOCS_DIR.resolve() not in candidate.parents and candidate != DOCS_DIR.resolve():
        raise FileNotFoundError("허용되지 않은 문서 경로입니다.")
    if not candidate.is_file() or candidate.suffix.lower() != ".md":
        raise FileNotFoundError("문서를 찾을 수 없습니다.")
    return candidate


app = FastAPI(title=APP_NAME, version="0.1.0")
cors_origins = parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def healthcheck() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "app": APP_NAME,
        }
    )


@app.get("/session")
async def session_info() -> JSONResponse:
    return JSONResponse(
        {
            "app": APP_NAME,
            "model": MODEL_NAME,
            "voice": VOICE_NAME,
            "input_sample_rate": INPUT_SAMPLE_RATE,
            "output_sample_rate": OUTPUT_SAMPLE_RATE,
            "frontend_url": "/static/index.html",
            "gemini_api_configured": has_valid_api_key(),
            "supabase_storage_configured": has_supabase_storage(),
            "cors_origins": cors_origins,
            "session_management": {
                "audio_only_limit_minutes": 15,
                "connection_limit_minutes": 10,
                "context_window_compression": True,
                "session_resumption": "memory-backed",
            },
        }
    )


@app.get("/workspace/docs", response_class=HTMLResponse)
async def docs_index() -> HTMLResponse:
    return HTMLResponse(render_docs_index())


@app.get("/workspace/docs/{doc_path:path}", response_class=HTMLResponse)
async def docs_view(doc_path: str) -> HTMLResponse:
    try:
        document = resolve_doc_path(doc_path)
    except FileNotFoundError:
        return HTMLResponse("<h1>문서를 찾을 수 없습니다.</h1>", status_code=404)

    return HTMLResponse(
        render_markdown_document(
            title=document.name,
            body=document.read_text(encoding="utf-8"),
            relative_path=document.relative_to(BASE_DIR).as_posix(),
        )
    )


@app.websocket("/ws")
async def websocket_bridge(websocket: WebSocket) -> None:
    await websocket.accept()

    client_id = websocket.query_params.get("client_id") or str(uuid4())
    conversation_key = websocket.query_params.get("conversation_key") or str(uuid4())
    store = ConversationStore(
        conversation_key=conversation_key,
        external_client_id=client_id,
        resumed=bool(SESSION_HANDLES.get(client_id)),
        model_name=MODEL_NAME,
        voice_name=VOICE_NAME,
    )
    previous_handle = SESSION_HANDLES.get(client_id)
    session_stack: Optional[AsyncExitStack] = None
    logger.info(
        "브라우저 연결 수락: client_id=%s conversation_key=%s resumed=%s",
        client_id,
        conversation_key,
        bool(previous_handle),
    )

    try:
        client = get_gemini_client()
    except RuntimeError as exc:
        await safe_send_json(
            websocket,
            {
                "type": "error",
                "message": str(exc),
            },
        )
        await websocket.close(code=1011, reason="GOOGLE_API_KEY missing")
        return

    await safe_send_json(
        websocket,
        {
            "type": "status",
            "state": "connecting",
            "message": "가준이를 깨우는 중",
        },
    )

    try:
        session_stack, session, resumed = await open_live_session(
            client,
            client_id,
            conversation_key,
            previous_handle,
        )
        store.resumed = resumed
        await store.initialize()
        logger.info(
            "Gemini Live 연결 성공: client_id=%s conversation_key=%s resumed=%s",
            client_id,
            conversation_key,
            resumed,
        )
        await safe_send_json(
            websocket,
            {
                "type": "ready",
                "client_id": client_id,
                "conversation_key": conversation_key,
                "resumed": resumed,
            },
        )
        await safe_send_json(
            websocket,
            {
                "type": "status",
                "state": "listening",
                "message": "듣는 중",
            },
        )
        await run_bridge(websocket, session, client_id, store)
    except WebSocketDisconnect as exc:
        store.connection_close_reason = f"websocket_disconnect:{getattr(exc, 'code', 'unknown')}"
        logger.info("브라우저 연결 종료: client_id=%s conversation_key=%s", client_id, conversation_key)
    except Exception as exc:
        await store.fail_session(str(exc))
        store.connection_close_reason = "bridge_error"
        store.connection_error_message = str(exc)
        logger.exception("Live API 브리지 오류")
        with suppress(Exception):
            await safe_send_json(
                websocket,
                {
                    "type": "error",
                    "message": f"연결이 끊겼어요. 다시 연결해주세요. ({exc})",
                },
            )
            await websocket.close(code=1011, reason="bridge error")
    finally:
        if session_stack is not None:
            with suppress(Exception):
                await session_stack.aclose()
        await store.close_connection()
