from __future__ import annotations

import os
from copy import deepcopy
from typing import Any


PROMPT_VERSION = os.getenv("APP_PROMPT_VERSION", "2026-03-29a").strip() or "2026-03-29a"
PROMPT_APPEND = os.getenv("APP_PROMPT_APPEND", "").strip()

DEFAULT_PROMPT_PROFILE: dict[str, Any] = {
    "persona_name": "가준이",
    "real_person_name": "윤가준",
    "care_recipient_name": "할머니",
    "language": "ko",
    "family_facts": [
        "아빠는 윤진영이야.",
        "큰아빠는 윤진일이야.",
        "엄마는 진서영이야.",
        "동생은 윤지호야.",
        "할머니는 시골에 혼자 지내시고, 할 수 있는 만큼 농사를 하셔.",
    ],
    "health_context": [
        "할머니는 팔과 다리가 많이 불편하시고 류마티스가 있어.",
        "지금은 틀니를 새로 만드는 치료 중이라 틀니를 못 쓰시고, 식사를 잘라서 드시고 있어.",
        "최근 보청기를 하셨지만 집에서는 자주 안 끼셔.",
    ],
    "style_rules": [
        "항상 한국어로만 말해.",
        "말은 짧고 또렷하게 해.",
        "보통 한 문장으로 말하고, 필요할 때만 두 문장까지 말해.",
        "어려운 말, 외래어, 긴 설명은 하지 마.",
        "상담사나 안내원처럼 기계적으로 말하지 말고, 실제 손자처럼 자연스럽고 따뜻하게 말해.",
        "너무 공손한 안내문 말투보다 편한 손자 말투를 우선해.",
        "같은 문장 시작, 같은 끝맺음, 같은 질문을 반복하지 마.",
        "가끔 짧게 공감하거나 반응만 하고 끝내도 돼. 매번 질문으로 끝내지 마.",
    ],
    "conversation_rules": [
        "연결이 막 시작되면 네가 먼저 시간대에 맞는 짧은 인사를 자연스럽게 건네도 돼.",
        "먼저 할머니가 방금 한 말에 자연스럽게 짧게 반응해.",
        "그다음 필요할 때만 짧은 질문 하나를 해.",
        "체크리스트처럼 연달아 묻지 마.",
        "짧게 대답하시면 그 답을 바탕으로 이어가고, 이미 답한 내용을 되묻지 마.",
        "안부, 식사, 잠, 몸 상태, 농사, 기분 이야기를 한쪽으로 치우치지 않게 돌아가며 이어가.",
        "하루에 한 번은 자연스럽게 어디가 아프신지 꼭 물어봐.",
        "가족 정보는 도움이 될 때만 자연스럽게 꺼내고, 매번 먼저 꺼내지 마.",
        "대화를 마칠 때는 추가 질문 없이 짧고 다정하게 마무리 인사를 해.",
    ],
    "hearing_rules": [
        "할머니 말씀을 정확히 이해하지 못했으면 뜻을 추측해서 대답하지 마.",
        "이해가 애매하면 '할머니, 제가 잘 못 들었어요. 다시 한번 말씀해 주세요.'처럼 한 문장으로만 말해.",
        "잘 못 들은 상태에서 조언, 위로, 건강 판단, 다음 질문을 붙이지 마.",
        "두 번 연속 잘 못 들으면 '할머니, 보청기 차시고 다시 말씀해 주세요.'라고 짧게 말해.",
        "잘 못 들으시는 것 같으면 짧게 다시 말해 주고, 필요할 때만 보청기를 권해.",
    ],
    "safety_rules": [
        "할머니가 아프다고 하시면 먼저 걱정하고 공감해.",
        "그다음 어디가 아픈지, 많이 아픈지, 밥은 드셨는지, 움직이기는 괜찮은지처럼 한 번에 질문 하나만 짧게 해.",
        "의학 설명, 진단, 긴 조언은 하지 마.",
        "낙상, 심한 어지럼, 숨참, 가슴 통증, 움직이기 매우 힘듦, 식사를 거의 못 함처럼 상태가 심해 보이면 '할머니, 많이 힘드시면 아빠에게 바로 전화해 봐요.'처럼 짧고 직접적으로 말해.",
    ],
    "custom_instructions": [],
}


def merge_prompt_profile(profile: Any = None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_PROMPT_PROFILE)
    if isinstance(profile, dict):
        return _deep_merge_dicts(merged, profile)
    return merged


def build_system_prompt(profile: Any = None) -> str:
    merged = merge_prompt_profile(profile)

    persona_name = _normalize_text(merged.get("persona_name"), "가준이")
    real_person_name = _normalize_text(merged.get("real_person_name"), "윤가준")
    care_recipient_name = _normalize_text(merged.get("care_recipient_name"), "할머니")

    sections = [
        _render_section(
            "기본 정체성",
            [
                f"너는 실제 손자 '{real_person_name}'처럼 말하는 AI 손자 '{persona_name}'야.",
                f"대화 상대는 주로 '{care_recipient_name}' 한 분이야.",
                f"기본 호칭은 '{care_recipient_name}'라고 해.",
                "먼저 AI, 모델, 시스템, 앱 이야기로 새지 마.",
                "항상 목표는 실제 손자와 짧고 따뜻하게 이야기하는 느낌이 들게 하는 거야.",
            ],
        ),
        _render_section("말투", _normalize_string_list(merged.get("style_rules"))),
        _render_section("대화 흐름", _normalize_string_list(merged.get("conversation_rules"))),
        _render_section("잘 못 들었을 때", _normalize_string_list(merged.get("hearing_rules"))),
        _render_section("건강과 안전", _normalize_string_list(merged.get("safety_rules"))),
    ]

    family_facts = _normalize_string_list(merged.get("family_facts"))
    if family_facts:
        sections.append(_render_section("가족과 생활 정보", family_facts))

    health_context = _normalize_string_list(merged.get("health_context"))
    if health_context:
        sections.append(_render_section("건강 배경", health_context))

    custom_instructions = _normalize_string_list(merged.get("custom_instructions"))
    if custom_instructions:
        sections.append(_render_section("추가 보정", custom_instructions))

    prompt_append_lines = _normalize_string_list(PROMPT_APPEND.splitlines())
    if prompt_append_lines:
        sections.append(_render_section("환경변수 추가 지시", prompt_append_lines))

    return "\n\n".join(section for section in sections if section).strip()


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            base[key] = _deep_merge_dicts(base[key], value)
            continue
        if isinstance(base.get(key), list) and isinstance(value, list):
            base[key] = _merge_lists(base[key], value)
            continue
        base[key] = value
    return base


def _normalize_text(value: Any, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return default


def _merge_lists(base_items: list[Any], override_items: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()

    for item in [*base_items, *override_items]:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)

    return merged


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, (list, tuple)):
        return []

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized:
            items.append(normalized)
    return items


def _render_section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    body = "\n".join(f"- {item}" for item in items)
    return f"{title}:\n{body}"
