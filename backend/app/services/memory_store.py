import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.models.deck import Slide
from app.models.memory import DeckMemory, MemoryEvent, SlideMemory


MAX_EVENTS = 160


def load_memory(deck_id: str) -> DeckMemory:
    path = _memory_path(deck_id)
    if not path.exists():
        return DeckMemory(deck_id=deck_id)
    return DeckMemory.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_memory(memory: DeckMemory) -> None:
    _memory_path(memory.deck_id).write_text(memory.model_dump_json(indent=2), encoding="utf-8")


def append_memory_event(
    deck_id: str,
    event_type: str,
    summary: str,
    slide_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> DeckMemory:
    memory = load_memory(deck_id)
    memory.events.append(
        MemoryEvent(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
            type=event_type,
            summary=summary,
            slide_id=slide_id,
            metadata=metadata or {},
        )
    )
    memory.events = memory.events[-MAX_EVENTS:]
    save_memory(memory)
    return memory


def record_user_intent(deck_id: str, instruction: str, scope: str, style_name: str) -> DeckMemory:
    memory = load_memory(deck_id)
    memory.latest_user_intent = instruction
    memory.style = style_name
    audience = _audience_from_text(f"{instruction}\n{style_name}")
    if audience:
        memory.audience = audience
        memory.global_constraints = _constraints_for_audience(memory.global_constraints, audience)
    if not memory.deck_goal or not scope.startswith("第 "):
        memory.deck_goal = _goal_from_instruction(instruction, scope)
    memory.global_constraints = _merge_constraints(
        memory.global_constraints,
        _constraints_from_text(f"{instruction}\n{style_name}"),
    )
    memory.events.append(
        MemoryEvent(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
            type="user_intent",
            summary=f"用户要求：{instruction}",
            metadata={"scope": scope, "style": style_name},
        )
    )
    memory.events = memory.events[-MAX_EVENTS:]
    save_memory(memory)
    return memory


def record_agent_note_change(
    deck_id: str,
    slide: Slide,
    instruction: str,
    style_name: str,
    content: str,
    declared_slide_id: str | None = None,
) -> DeckMemory:
    memory = load_memory(deck_id)
    slide_memory = memory.slides.get(slide.id) or SlideMemory(slide_id=slide.id)
    slide_memory.last_change = f"Agent 按「{style_name}」处理讲稿：{_compact(content, 80)}"
    slide_memory.notes_status = "agent_generated"
    if not slide_memory.role:
        slide_memory.role = _default_slide_role(slide.index)
    memory.slides[slide.id] = slide_memory

    metadata = {"style": style_name, "instruction": _compact(instruction, 120)}
    if declared_slide_id and declared_slide_id != slide.id:
        metadata["declared_slide_id"] = declared_slide_id
        metadata["executed_slide_id"] = slide.id

    memory.events.append(
        MemoryEvent(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
            type="agent_note_change",
            summary=f"第 {slide.index} 页讲稿已由 Agent 更新。",
            slide_id=slide.id,
            metadata=metadata,
        )
    )
    memory.events = memory.events[-MAX_EVENTS:]
    save_memory(memory)
    return memory


def record_manual_note_update(deck_id: str, slide: Slide, notes: str) -> DeckMemory:
    memory = load_memory(deck_id)
    slide_memory = memory.slides.get(slide.id) or SlideMemory(slide_id=slide.id)
    slide_memory.last_change = f"用户手动保存讲稿：{_compact(notes, 80)}"
    slide_memory.notes_status = "user_edited"
    if not slide_memory.role:
        slide_memory.role = _default_slide_role(slide.index)
    memory.slides[slide.id] = slide_memory
    memory.events.append(
        MemoryEvent(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
            type="manual_note_update",
            summary=f"用户手动保存第 {slide.index} 页讲稿。",
            slide_id=slide.id,
        )
    )
    memory.events = memory.events[-MAX_EVENTS:]
    save_memory(memory)
    return memory


def record_note_reset(deck_id: str, slide: Slide) -> DeckMemory:
    memory = load_memory(deck_id)
    slide_memory = memory.slides.get(slide.id) or SlideMemory(slide_id=slide.id)
    slide_memory.last_change = "用户重置为 PPT 原始备注。"
    slide_memory.notes_status = "reset_to_original"
    if not slide_memory.role:
        slide_memory.role = _default_slide_role(slide.index)
    memory.slides[slide.id] = slide_memory
    memory.events.append(
        MemoryEvent(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).isoformat(),
            type="note_reset",
            summary=f"用户将第 {slide.index} 页讲稿还原为原始备注。",
            slide_id=slide.id,
        )
    )
    memory.events = memory.events[-MAX_EVENTS:]
    save_memory(memory)
    return memory


def build_memory_context(deck_id: str, slide_id: str | None = None) -> str:
    memory = load_memory(deck_id)
    parts = [
        "这是该 PPT 的持久化记忆，请优先遵守用户已经形成的意图和约束。",
        f"整份 PPT 目标：{memory.deck_goal or '尚未形成明确目标'}",
        f"目标听众：{memory.audience or '未明确'}",
        f"当前风格：{memory.style or '未明确'}",
        f"最近用户意图：{memory.latest_user_intent or '无'}",
    ]
    if memory.global_constraints:
        parts.append("全局约束：" + "；".join(memory.global_constraints))
    if slide_id and slide_id in memory.slides:
        slide_memory = memory.slides[slide_id]
        parts.append(
            "当前页记忆："
            f"角色={slide_memory.role or '未定义'}；"
            f"状态={slide_memory.notes_status or '未知'}；"
            f"最近修改={slide_memory.last_change or '无'}"
        )
        if slide_memory.user_feedback:
            parts.append("当前页用户反馈：" + "；".join(slide_memory.user_feedback[-5:]))
    recent_events = memory.events[-8:]
    if recent_events:
        parts.append("最近操作记录：")
        parts.extend(f"- {event.summary}" for event in recent_events)
    return "\n".join(parts)


def _memory_path(deck_id: str) -> Path:
    return get_settings().memory_dir / f"{deck_id}.json"


def _audience_from_text(text: str) -> str:
    if re.search(r"小朋友|儿童|孩子|低龄|children|kid", text, re.IGNORECASE):
        return "小朋友"
    if re.search(r"商务|客户|投资人|正式|严肃|克制|专业|路演|外宾|外国|海外|国际|外方|business|foreign|international|overseas", text, re.IGNORECASE):
        return "商务听众"
    if re.search(r"领导|高管|老板|管理层|决策层|决策者|executive", text, re.IGNORECASE):
        return "高管或决策层"
    return ""


def _constraints_from_text(text: str) -> list[str]:
    constraints = ["讲稿用于语音播报，需要自然口语、短句和清晰转场"]
    if re.search(r"小朋友|儿童|孩子|低龄|children|kid", text, re.IGNORECASE):
        constraints.extend(
            [
                "面向小朋友时减少专业术语，用简单类比解释概念",
                "只有第一页可以完整开场，后续页面不要重复问候",
            ]
        )
    if re.search(r"商务|商业|客户|投资人|正式|严肃|克制|专业|路演|外宾|外国|海外|国际|外方|business|foreign|international|overseas", text, re.IGNORECASE):
        constraints.extend(
            [
                "商务风格需要正式克制，先讲结论，再解释依据",
                "减少儿童化、拟人化和过度活泼表达",
            ]
        )
    if re.search(r"外宾|外国|海外|国际|外方|foreign|international|overseas", text, re.IGNORECASE):
        constraints.extend(
            [
                "面向外宾时需要确认并保持目标语言一致",
                "对本土机构、政策和案例适当补充背景，避免默认听众熟悉中文语境",
            ]
        )
    if re.search(r"领导|高管|老板|管理层|决策层|决策者|executive", text, re.IGNORECASE):
        constraints.extend(
            [
                "面向领导时要先给判断和价值，再补充关键依据",
                "压缩铺垫和细节，突出风险、收益和下一步建议",
            ]
        )
    if re.search(r"全部|所有|整份|每页|whole|all", text, re.IGNORECASE):
        constraints.append("批量处理时保持整份 PPT 的叙事连续性")
    return constraints


def _constraints_for_audience(existing: list[str], audience: str) -> list[str]:
    if audience == "小朋友":
        blocked = ["商务风格", "儿童化"]
    elif audience == "商务听众":
        blocked = ["小朋友", "儿童", "低龄"]
    else:
        return existing
    return [item for item in existing if not any(word in item for word in blocked)]


def _merge_constraints(existing: list[str], additions: list[str]) -> list[str]:
    merged = list(existing)
    for item in additions:
        if item not in merged:
            merged.append(item)
    return merged[-12:]


def _goal_from_instruction(instruction: str, scope: str) -> str:
    return f"根据用户要求处理{scope}讲稿：{_compact(instruction, 80)}"


def _default_slide_role(index: int) -> str:
    if index == 1:
        return "开场页"
    return "内容页"


def _compact(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
