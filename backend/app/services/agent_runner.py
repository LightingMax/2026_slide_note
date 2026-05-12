import json
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


def list_style_presets() -> list[AgentStylePreset]:
    return list(STYLE_PRESETS.values())


def create_run(payload: AgentRunCreate) -> str:
    run_id = uuid.uuid4().hex
    _RUNS[run_id] = payload
    return run_id


def stream_run(run_id: str) -> Generator[str, None, None]:
    payload = _RUNS.get(run_id)
    if payload is None:
        yield _event("error", {"message": "Agent run not found"})
        return

    try:
        yield _event("progress", {"message": "收到请求，正在创建 PPT 讲稿任务。"})
        deck = load_deck(payload.deck_id)
        yield _event("progress", {"message": "正在读取演示文稿、当前页内容和原始备注。"})

        slide = next((item for item in deck.slides if item.id == payload.slide_id), None)
        if slide is None:
            yield _event("error", {"message": "Slide not found"})
            return

        preset = STYLE_PRESETS.get(payload.style_preset, STYLE_PRESETS["narration"])
        yield _event("progress", {"message": f"已应用风格：{preset.name}。"})
        yield _event("progress", {"message": "正在调用模型生成可执行动作。"})

        response = generate_note(
            slide,
            payload.instruction,
            [item.model_dump() for item in payload.messages],
            preset.description,
        )
        yield _event("assistant", response.model_dump())

        changed = False
        for action in response.actions:
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
            yield _event("progress", {"message": "当前页讲稿已写入并保存。"})

        yield _event("done", {"deck": deck.model_dump()})
    except RuntimeError as exc:
        yield _event("error", {"message": str(exc)})
    finally:
        _RUNS.pop(run_id, None)


def _event(name: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"

