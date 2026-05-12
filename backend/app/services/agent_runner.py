import json
import re
import uuid
from collections.abc import Generator

from app.models.deck import AgentRunCreate, AgentStylePreset
from app.services.ark_client import generate_note
from app.services.storage import load_deck, save_deck


STYLE_PRESETS = {
    "narration": AgentStylePreset(
        id="narration",
        name="自然讲稿",
        description="自然口语、短句、转场顺滑，适合直接语音播报。",
    ),
    "business": AgentStylePreset(
        id="business",
        name="商务汇报",
        description="正式、克制、结论清晰，适合路演、汇报和商业沟通。",
    ),
    "children": AgentStylePreset(
        id="children",
        name="小朋友友好",
        description="亲切、简单、少术语，多用类比，适合低龄听众理解。",
    ),
    "executive": AgentStylePreset(
        id="executive",
        name="高管简报",
        description="先结论后依据，压缩细节，强调判断、风险和下一步。",
    ),
    "sales": AgentStylePreset(
        id="sales",
        name="产品演示",
        description="突出痛点、价值、差异化和行动号召，语气更有感染力。",
    ),
}

_RUNS: dict[str, AgentRunCreate] = {}
_CANCELLED_RUNS: set[str] = set()


def list_style_presets() -> list[AgentStylePreset]:
    return list(STYLE_PRESETS.values())


def create_run(payload: AgentRunCreate) -> str:
    run_id = uuid.uuid4().hex
    _RUNS[run_id] = payload
    return run_id


def cancel_run(run_id: str) -> bool:
    if run_id not in _RUNS:
        return False
    _CANCELLED_RUNS.add(run_id)
    return True


def stream_run(run_id: str) -> Generator[str, None, None]:
    payload = _RUNS.get(run_id)
    if payload is None:
        yield _event("error", {"message": "Agent run not found"})
        return

    try:
        yield _event("progress", {"message": "收到请求，正在创建 PPT 讲稿任务。"})
        deck = load_deck(payload.deck_id)
        yield _event("progress", {"message": "正在读取演示文稿、当前页内容和原始备注。"})

        context_text = _context_text(payload.instruction, payload.messages)
        deck_scope = _is_deck_scope(payload.instruction)
        target_slides = _resolve_target_slides(deck.slides, payload.slide_id, deck_scope)
        if not target_slides:
            yield _event("error", {"message": "Slide not found"})
            return
        scope_label = "整份演示文稿" if deck_scope else f"第 {target_slides[0].index} 页"
        yield _event("progress", {"message": f"已识别任务范围：{scope_label}。"})

        preset = _resolve_style_preset(payload.style_preset, payload.instruction, context_text)
        yield _event("progress", {"message": f"已应用风格：{preset.name}。"})

        changed = False
        for position, slide in enumerate(target_slides, start=1):
            if _is_cancelled(run_id):
                yield _event("cancelled", {"message": "任务已停止，未继续处理剩余页面。"})
                return
            if len(target_slides) > 1:
                yield _event(
                    "progress",
                    {"message": f"正在处理第 {slide.index} 页（{position}/{len(target_slides)}）。"},
                )
            yield _event("progress", {"message": "正在调用模型生成可执行动作。"})

            response = generate_note(
                slide,
                _scoped_instruction(payload.instruction, len(target_slides)),
                [item.model_dump() for item in payload.messages],
                preset.description,
            )
            yield _event("assistant", response.model_dump())

            for action in response.actions:
                if _is_cancelled(run_id):
                    yield _event("cancelled", {"message": "任务已停止。"})
                    return
                yield _event("progress", {"message": f"正在执行动作：{action.label}。"})
                if action.type == "replace_notes" and action.slide_id == slide.id:
                    slide.notes = action.content
                    changed = True
                    yield _event(
                        "action",
                        {
                            "type": action.type,
                            "slide_id": action.slide_id,
                            "label": action.label,
                            "content": action.content,
                        },
                    )

        if changed:
            save_deck(deck)
            done_message = "所有目标页讲稿已写入并保存。" if len(target_slides) > 1 else "当前页讲稿已写入并保存。"
            yield _event("progress", {"message": done_message})

        yield _event("done", {"deck": deck.model_dump()})
    except RuntimeError as exc:
        yield _event("error", {"message": str(exc)})
    finally:
        _RUNS.pop(run_id, None)
        _CANCELLED_RUNS.discard(run_id)


def _event(name: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"


def _resolve_target_slides(slides, slide_id: str, deck_scope: bool):
    if deck_scope:
        return slides
    return [item for item in slides if item.id == slide_id]


def _is_deck_scope(instruction: str) -> bool:
    text = instruction.lower()
    patterns = [
        r"所有\s*(幻灯片|页面|页)",
        r"全部\s*(幻灯片|页面|页)",
        r"整份\s*(ppt|演示文稿|幻灯片|文档)",
        r"全\s*(ppt|演示文稿|幻灯片)",
        r"每一页",
        r"每页",
        r"all\s+slides",
        r"every\s+slide",
        r"whole\s+(deck|ppt|presentation)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _resolve_style_preset(style_preset: str, instruction: str, context_text: str) -> AgentStylePreset:
    explicit = _style_from_text(instruction)
    if explicit:
        return explicit
    contextual = _style_from_text(context_text)
    if contextual:
        return contextual
    if style_preset != "auto":
        return STYLE_PRESETS.get(style_preset, STYLE_PRESETS["narration"])
    return STYLE_PRESETS["narration"]


def _style_from_text(text: str) -> AgentStylePreset | None:
    text = text.lower()
    if re.search(r"小朋友|儿童|孩子|children|kid", text):
        return STYLE_PRESETS["children"]
    if re.search(r"商务|商业|路演|business", text):
        return STYLE_PRESETS["business"]
    if re.search(r"高管|老板|executive|brief", text):
        return STYLE_PRESETS["executive"]
    if re.search(r"销售|产品演示|demo|sales", text):
        return STYLE_PRESETS["sales"]
    if re.search(r"自然|口语|播报|narration", text):
        return STYLE_PRESETS["narration"]
    return None


def _scoped_instruction(instruction: str, target_count: int) -> str:
    if target_count <= 1:
        return instruction
    return (
        f"{instruction}\n\n这是一个整份 PPT 的批量任务。"
        "请只为当前这一页生成讲稿，保持所选风格一致，不要提到其他页的处理进度。"
    )


def _context_text(instruction: str, messages) -> str:
    recent = [
        item.content
        for item in messages[-12:]
        if item.role in {"user", "assistant"} and item.content
    ]
    recent.append(instruction)
    return "\n".join(reversed(recent))


def _is_cancelled(run_id: str) -> bool:
    return run_id in _CANCELLED_RUNS
