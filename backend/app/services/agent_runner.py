import json
import re
import uuid
from collections.abc import Generator
from dataclasses import dataclass

from app.models.deck import AgentRunCreate, AgentStylePreset
from app.services.ark_client import generate_note, resolve_task_instruction
from app.services.memory_store import build_memory_context, record_agent_note_change, record_user_intent
from app.services.storage import load_deck, save_deck


STYLE_PRESETS = {
    "narration": AgentStylePreset(
        id="narration",
        name="自然讲稿",
        description="自然口语、短句、转场顺滑，适合直接语音播报。保留原文关键信息，避免书面化堆砌，按连续演讲组织内容。",
    ),
    "business": AgentStylePreset(
        id="business",
        name="商务汇报",
        description="正式、克制、结论清晰，适合路演、汇报和商业沟通。先讲结论和业务价值，再解释依据与落地方式，避免夸张口号。",
    ),
    "children": AgentStylePreset(
        id="children",
        name="小朋友友好",
        description="亲切、简单、少术语，多用生活化类比，适合低龄听众理解。只在第一页问候，后续页面自然承接，不重复开场。",
    ),
    "executive": AgentStylePreset(
        id="executive",
        name="高管简报",
        description="先结论后依据，压缩细节，强调判断、风险、收益和下一步。语言直接，减少铺垫，突出管理层关心的决策信息。",
    ),
    "sales": AgentStylePreset(
        id="sales",
        name="产品演示",
        description="突出痛点、价值、差异化和行动号召，语气更有感染力。每页围绕客户收益展开，避免空泛宣传。",
    ),
}

_RUNS: dict[str, AgentRunCreate] = {}
_CANCELLED_RUNS: set[str] = set()


@dataclass(frozen=True)
class DeckNarrativePlan:
    overview: str
    slide_roles: dict[str, str]


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

        fallback_instruction = _resolve_effective_instruction(payload.instruction, payload.messages)
        if _should_use_local_intent_resolution(payload.instruction, payload.messages):
            instruction = fallback_instruction
        else:
            instruction = resolve_task_instruction(
                payload.instruction,
                [item.model_dump() for item in payload.messages],
                fallback_instruction,
                deck.filename,
                len(deck.slides),
            )
        if instruction != payload.instruction:
            yield _event("progress", {"message": "已根据最近会话规整当前任务意图。"})
        if _needs_language_clarification(instruction):
            yield _event(
                "assistant",
                {
                    "text": "",
                    "message": "我需要先确认讲稿语言：这次客户讲稿是要中文、英文、日文，还是其他语言？你可以回复“中文”“英文”“日文”“泰文”等。",
                    "actions": [],
                    "ui": _language_choice_ui(),
                },
            )
            yield _event("done", {"deck": deck.model_dump()})
            return

        current_scope = _is_current_slide_scope(instruction)
        deck_scope = _is_deck_scope(instruction) and not current_scope
        if _needs_scope_clarification(instruction, deck_scope, len(deck.slides)):
            yield _event(
                "assistant",
                {
                    "text": "",
                    "message": "我需要确认一下：这次是只修改当前页，还是应用到整份 PPT？你可以回复“当前页”或“全部文档”。",
                    "actions": [],
                    "ui": _scope_choice_ui(),
                },
            )
            yield _event("done", {"deck": deck.model_dump()})
            return
        target_slides = _resolve_target_slides(deck.slides, payload.slide_id, deck_scope)
        if not target_slides:
            yield _event("error", {"message": "Slide not found"})
            return
        scope_label = "整份演示文稿" if deck_scope else f"第 {target_slides[0].index} 页"
        preset = _resolve_style_preset(payload.style_preset, instruction, payload.messages)
        language_context = _language_context(instruction)
        language_label = _language_label(instruction)

        if _needs_plan_confirmation(instruction):
            yield _event(
                "assistant",
                {
                    "text": "",
                    "message": _plan_message(deck, target_slides, scope_label, preset, language_label, instruction),
                    "actions": [],
                    "ui": _plan_confirmation_ui(),
                },
            )
            yield _event("done", {"deck": deck.model_dump()})
            return

        yield _event("progress", {"message": f"已识别任务范围：{scope_label}。"})
        yield _event("progress", {"message": f"已应用风格：{preset.name}。"})
        if language_label:
            yield _event("progress", {"message": f"已识别讲稿语言：{language_label}。"})
        record_user_intent(payload.deck_id, instruction, scope_label, preset.name)
        yield _event("progress", {"message": "已写入本次用户意图到 PPT 记忆。"})
        narrative_plan = _build_narrative_plan(deck.slides, target_slides, preset, deck_scope)
        if len(target_slides) > 1:
            yield _event("progress", {"message": "已建立整份 PPT 的讲稿主线，后续页面会按页间承接生成。"})

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
                _scoped_instruction(instruction, len(target_slides)),
                [item.model_dump() for item in payload.messages],
                preset.description,
                _deck_context(
                    narrative_plan,
                    slide,
                    position,
                    len(target_slides),
                    build_memory_context(payload.deck_id, slide.id),
                    language_context,
                ),
            )
            yield _event("assistant", response.model_dump())

            for action in response.actions:
                if _is_cancelled(run_id):
                    yield _event("cancelled", {"message": "任务已停止。"})
                    return
                if action.type != "replace_notes" or not action.content.strip():
                    continue
                bound_action = {
                    "type": action.type,
                    "slide_id": slide.id,
                    "label": action.label,
                    "content": action.content,
                }
                if action.slide_id != slide.id:
                    yield _event(
                        "progress",
                        {
                            "message": (
                                f"模型声明目标页为 {action.slide_id}，当前执行页为 {slide.id}，"
                                "已按任务上下文校正。"
                            )
                        },
                    )
                yield _event("progress", {"message": f"正在执行动作：{action.label}。"})
                slide.notes = action.content
                changed = True
                record_agent_note_change(
                    payload.deck_id,
                    slide,
                    instruction,
                    preset.name,
                    action.content,
                    action.slide_id,
                )
                yield _event("action", bound_action)

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
        r"范围[：:\s]*(整份|全部|所有|全)",
        r"范围.*整份\s*(演示文稿|ppt|幻灯片|文档)",
        r"范围.*第\s*1\s*页.*第\s*\d+\s*页",
        r"整份.*第\s*1\s*页.*第\s*\d+\s*页",
        r"这次来的是.*客户.*讲稿",
        r"(客户|外宾|来宾|访客).*讲稿",
        r"给我.*讲稿",
        r"做.*讲稿",
        r"全部(的)?",
        r"全都",
        r"都要",
        r"所有(的)?",
        r"所有\s*(幻灯片|页面|页)",
        r"所有\s*风格",
        r"所有.*(换成|改成|迁移|修改)",
        r"全部\s*(幻灯片|页面|页)",
        r"全部\s*(文档|讲稿|备注|风格)",
        r"整份\s*(ppt|演示文稿|幻灯片|文档)",
        r"全\s*(ppt|演示文稿|幻灯片)",
        r"应用到\s*(全部|所有|整份|全)",
        r"(全部|所有|整份).*(应用|执行|修改|替换)",
        r"每一页",
        r"每页",
        r"all\s+slides",
        r"every\s+slide",
        r"whole\s+(deck|ppt|presentation)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _is_current_slide_scope(instruction: str) -> bool:
    text = instruction.lower()
    patterns = [
        r"用户补充：\s*当前页",
        r"用户补充：\s*当前页面",
        r"当前\s*(页|页面|幻灯片)",
        r"这一\s*(页|页面|张)",
        r"这\s*(页|张)",
        r"current\s+slide",
        r"this\s+slide",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _resolve_effective_instruction(instruction: str, messages) -> str:
    user_messages = _user_message_contents(messages)
    if user_messages and user_messages[-1] == instruction.strip():
        previous = user_messages[:-1]
    else:
        previous = user_messages

    if not (
        _is_scope_answer(instruction)
        or _is_language_answer(instruction)
        or _is_confirmation_answer(instruction)
        or _is_plan_revision(instruction, messages)
        or _is_plan_revision(instruction, previous)
    ):
        return instruction

    intent = _last_substantive_user_intent(previous)
    if not intent:
        return instruction

    supplements = _recent_supplements_after_intent(previous, intent)
    if not _is_confirmation_answer(instruction):
        supplements.append(instruction.strip())
    supplement_text = "\n".join(f"用户补充：{item}" for item in supplements)
    confirmation_text = f"\n用户确认：{instruction.strip()}" if _is_confirmation_answer(instruction) else ""
    return f"{intent}\n{supplement_text}{confirmation_text}"


def _should_use_local_intent_resolution(instruction: str, messages) -> bool:
    if "用户确认：" in instruction:
        return True

    user_messages = _user_message_contents(messages)
    if user_messages and user_messages[-1] == instruction.strip():
        previous = user_messages[:-1]
    else:
        previous = user_messages

    return bool(
        _is_frontend_style_plan(instruction)
        or _is_scope_answer(instruction)
        or _is_language_answer(instruction)
        or _is_confirmation_answer(instruction)
        or _is_plan_revision(instruction, messages)
        or _is_plan_revision(instruction, previous)
    )


def _user_message_contents(messages) -> list[str]:
    return [
        _message_content(item).strip()
        for item in messages
        if _message_role(item) == "user" and _message_content(item).strip()
    ]


def _is_frontend_style_plan(instruction: str) -> bool:
    return bool("风格模板" in instruction and _is_deck_scope(instruction))


def _message_role(item) -> str:
    if isinstance(item, dict):
        return str(item.get("role") or "")
    return str(getattr(item, "role", "") or "")


def _message_content(item) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or "")
    return str(getattr(item, "content", "") or "")


def _last_substantive_user_intent(messages: list[str]) -> str:
    for item in reversed(messages):
        if _is_plan_revision(item, messages):
            continue
        if not _is_scope_answer(item) and not _is_language_answer(item) and not _is_confirmation_answer(item):
            return item
    return ""


def _recent_supplements_after_intent(messages: list[str], intent: str) -> list[str]:
    supplements = []
    seen_intent = False
    for item in messages:
        if item == intent:
            seen_intent = True
            supplements = []
            continue
        if seen_intent and (_is_scope_answer(item) or _is_language_answer(item) or _is_plan_revision(item, messages)):
            supplements.append(item)
    return supplements[-4:]


def _is_scope_answer(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(r"(全部|全都|所有|全部文档|整份|整份ppt|全ppt|全部ppt|all|whole)", normalized)
        or re.fullmatch(r"(当前页|当前页面|这一页|这页|当前|current|this slide)", normalized)
    )


def _is_language_answer(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(
            r"(中文|汉语|普通话|英文|英语|english|阿拉伯文|阿拉伯语|arabic|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish)",
            normalized,
        )
        or re.fullmatch(
            r"(用|改成|换成)?(中文|汉语|普通话|英文|英语|english|阿拉伯文|阿拉伯语|arabic|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish)(讲稿|版本)?",
            normalized,
        )
        or bool(re.search(r"(我要|我想|需要|用|改成|换成).{0,12}(中文|汉语|普通话|英文|英语|english|阿拉伯文|阿拉伯语|arabic|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish)", normalized))
        or bool(re.search(r"(中文|汉语|普通话|英文|英语|english|阿拉伯文|阿拉伯语|arabic|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish).{0,8}(客户|团队|语言|讲稿)", normalized))
    )


def _is_plan_revision(text: str, previous_messages: list[str]) -> bool:
    if not _has_pending_plan(previous_messages):
        return False
    return bool(
        re.search(r"不对|更正|改成|换成|通知说|其实|还是|不是|客户是|团队|语言|受众|范围|风格", text, re.IGNORECASE)
        or _has_style_intent(text)
    )


def _has_pending_plan(messages: list[str]) -> bool:
    for item in reversed(messages[-8:]):
        content = _message_content(item) if not isinstance(item, str) else item
        role = _message_role(item)
        if (role == "user" or isinstance(item, str)) and _is_confirmation_answer(content):
            return False
        if "我先给出执行计划" in content or "确认后再修改 PPT 备注" in content:
            return True
    return False


def _is_confirmation_answer(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(
            r"(确认|确认执行|开始执行|执行|开始|开始生成|开始吧|可以|可以了|好的|好|行|就这样|按这个来|可以执行|按计划执行|没问题|ok|okay|yes|go)",
            normalized,
        )
    )


def _needs_plan_confirmation(instruction: str) -> bool:
    return not re.search(r"用户确认：", instruction)


def _plan_message(deck, target_slides, scope_label: str, preset: AgentStylePreset, language_label: str, instruction: str) -> str:
    language = language_label or "未指定，保持原讲稿语言"
    slide_count = len(target_slides)
    start_index = target_slides[0].index if target_slides else 0
    end_index = target_slides[-1].index if target_slides else 0
    scope_detail = f"{scope_label}，共 {slide_count} 页"
    if slide_count > 1:
        scope_detail = f"{scope_label}，共 {slide_count} 页，第 {start_index} 页到第 {end_index} 页"

    return (
        "我先给出执行计划，确认后再修改 PPT 备注。\n\n"
        f"任务理解：{_compact_text(instruction, 140)}\n"
        f"文件：{deck.filename}\n"
        f"范围：{scope_detail}\n"
        f"风格：{preset.name}（{preset.description}）\n"
        f"语言：{language}\n"
        "叙事：按整份 PPT 的连续演讲处理，第一页负责开场，中间页自然承接，最后一页收束。\n"
        "写入：确认后会替换目标页的当前页讲稿，并更新 PPT 记忆。\n\n"
        "请回复“确认执行”开始，或继续补充语言、范围、受众、风格等要求。"
    )


def _language_choice_ui() -> dict:
    return {
        "type": "choice",
        "id": "language",
        "title": "选择讲稿语言",
        "mode": "radio",
        "options": [
            {"label": "中文", "value": "中文", "description": "适合中文接待或内部汇报。"},
            {"label": "英文", "value": "英文", "description": "适合国际商务沟通。"},
            {"label": "日文", "value": "日文", "description": "适合日本客户或日语场景。"},
            {"label": "阿拉伯语", "value": "阿拉伯语", "description": "适合中东客户或阿语场景。"},
            {"label": "泰文", "value": "泰文", "description": "适合泰语客户。"},
        ],
    }


def _scope_choice_ui() -> dict:
    return {
        "type": "choice",
        "id": "scope",
        "title": "选择修改范围",
        "mode": "buttons",
        "options": [
            {"label": "当前页", "value": "当前页", "description": "只替换当前选中页讲稿。"},
            {"label": "全部文档", "value": "全部文档", "description": "替换整份 PPT 的讲稿。"},
        ],
    }


def _plan_confirmation_ui() -> dict:
    return {
        "type": "confirmation",
        "id": "execute_plan",
        "title": "是否开始执行？",
        "mode": "buttons",
        "options": [
            {"label": "确认执行", "value": "确认执行", "description": "按上述计划开始修改讲稿。"},
        ],
    }


def _needs_language_clarification(instruction: str) -> bool:
    return _mentions_language_ambiguous_customer(instruction) and not _mentions_language(instruction)


def _mentions_foreign_audience(text: str) -> bool:
    return bool(
        re.search(
            r"外宾|外国|海外|国际|外方|中东|阿拉伯客户|foreign|international|overseas|middle\s*east",
            text,
            re.IGNORECASE,
        )
    )


def _mentions_language_ambiguous_customer(text: str) -> bool:
    return _mentions_foreign_audience(text) or bool(
        re.search(r"松下|panasonic|索尼|sony|丰田|toyota|本田|honda|日本客户|日本的客户|日韩客户", text, re.IGNORECASE)
    )


def _mentions_language(text: str) -> bool:
    return bool(
        re.search(
            r"中文|汉语|普通话|英文|英语|english|阿拉伯文|阿拉伯语|arabic|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish",
            text,
            re.IGNORECASE,
        )
        or _mentions_middle_east(text)
    )


def _needs_scope_clarification(instruction: str, deck_scope: bool, slide_count: int) -> bool:
    if slide_count <= 1 or deck_scope or _is_current_slide_scope(instruction):
        return False
    text = instruction.lower()
    asks_for_edit = re.search(
        r"需要|要|生成|改成|换成|变成|转成|迁移|应用|修改|调整|润色|重写|优化|面向|适合|style|rewrite|apply",
        text,
    )
    mentions_style = _has_style_intent(text)
    return bool(asks_for_edit and mentions_style)


def _resolve_style_preset(style_preset: str, instruction: str, messages) -> AgentStylePreset:
    explicit = _style_from_text(instruction)
    if explicit:
        return explicit
    for item in reversed(messages[-12:]):
        if item.role not in {"user", "assistant"} or not item.content:
            continue
        contextual = _style_from_text(item.content)
        if contextual:
            return contextual
    if style_preset != "auto":
        return STYLE_PRESETS.get(style_preset, STYLE_PRESETS["narration"])
    return STYLE_PRESETS["narration"]


def _style_from_text(text: str) -> AgentStylePreset | None:
    text = text.lower()
    if re.search(r"小朋友|儿童|孩子|children|kid", text):
        return STYLE_PRESETS["children"]
    if re.search(r"商务|商业|客户|投资人|正式|严肃|克制|专业|路演|中东|外宾|外国|海外|国际|外方|business|middle\s*east|foreign|international|overseas", text):
        return STYLE_PRESETS["business"]
    if re.search(r"外宾|外国|海外|国际|外方|foreign|international|overseas", text):
        return STYLE_PRESETS["business"]
    if re.search(r"领导|高管|老板|管理层|决策层|决策者|executive|brief", text):
        return STYLE_PRESETS["executive"]
    if re.search(r"销售|产品演示|demo|sales", text):
        return STYLE_PRESETS["sales"]
    if re.search(r"自然|口语|播报|narration", text):
        return STYLE_PRESETS["narration"]
    return None


def _has_style_intent(text: str) -> bool:
    return bool(
        _style_from_text(text)
        or re.search(r"风格|语气|口吻|受众|面向|听众|汇报|汇报对象|style|tone|audience", text)
    )


def _language_context(instruction: str) -> str:
    if re.search(r"阿拉伯文|阿拉伯语|arabic", instruction, re.IGNORECASE):
        return "目标语言：阿拉伯语。content 字段必须使用阿拉伯语。"
    if re.search(r"英文|英语|english", instruction, re.IGNORECASE):
        return "目标语言：英文。content 字段必须使用英文。"
    if re.search(r"中文|汉语|普通话", instruction, re.IGNORECASE):
        return "目标语言：中文。content 字段必须使用中文。"
    if re.search(r"日文|日语|japanese", instruction, re.IGNORECASE):
        return "目标语言：日文。content 字段必须使用日文。"
    if re.search(r"松下|panasonic|索尼|sony|丰田|toyota|本田|honda|日本客户|日本的客户", instruction, re.IGNORECASE):
        return "目标语言：日文。用户已确认使用日文时，content 字段必须使用日文。"
    if re.search(r"泰文|泰语|thai", instruction, re.IGNORECASE):
        return "目标语言：泰文。content 字段必须使用泰文。"
    if _mentions_middle_east(instruction):
        return "目标语言：阿拉伯语。用户提到中东客户时，默认生成阿拉伯语讲稿。content 字段必须使用阿拉伯语，不要输出中文讲稿。"
    return ""


def _language_label(instruction: str) -> str:
    if re.search(r"阿拉伯文|阿拉伯语|arabic", instruction, re.IGNORECASE):
        return "阿拉伯语"
    if re.search(r"英文|英语|english", instruction, re.IGNORECASE):
        return "英文"
    if re.search(r"中文|汉语|普通话", instruction, re.IGNORECASE):
        return "中文"
    if re.search(r"日文|日语|japanese", instruction, re.IGNORECASE):
        return "日文"
    if re.search(r"松下|panasonic|索尼|sony|丰田|toyota|本田|honda|日本客户|日本的客户", instruction, re.IGNORECASE):
        return "日文"
    if re.search(r"泰文|泰语|thai", instruction, re.IGNORECASE):
        return "泰文"
    if _mentions_middle_east(instruction):
        return "阿拉伯语"
    return ""


def _mentions_middle_east(text: str) -> bool:
    return bool(re.search(r"中东|middle\s*east|阿拉伯客户", text, re.IGNORECASE))


def _scoped_instruction(instruction: str, target_count: int) -> str:
    if target_count <= 1:
        return instruction
    return (
        f"{instruction}\n\n这是一个整份 PPT 的批量任务。"
        "请只为当前这一页生成讲稿，保持所选风格一致，不要提到其他页的处理进度。"
    )


def _build_narrative_plan(all_slides, target_slides, preset: AgentStylePreset, deck_scope: bool) -> DeckNarrativePlan:
    if len(all_slides) <= 1:
        return DeckNarrativePlan(overview="单页讲稿任务。", slide_roles={})

    outline = []
    for slide in all_slides:
        title = slide.title or f"第 {slide.index} 页"
        summary = _compact_text(slide.text or slide.notes or "")
        outline.append(f"第 {slide.index} 页：{title}。{summary}")

    slide_roles = {}
    first_index = all_slides[0].index
    last_index = all_slides[-1].index
    for slide in target_slides:
        if slide.index == first_index:
            role = "开场页：可以有简短开场，交代主题和听众期待。"
        elif slide.index == last_index:
            role = "收束页：承接前文，做总结或行动引导，不要重新问候。"
        else:
            role = "内容展开页：直接承接上一页，解释本页重点，不要重新开场或问候。"
        slide_roles[slide.id] = role

    task_scope = "整份 PPT 批量讲稿任务" if deck_scope else "当前页讲稿任务"
    overview = (
        f"当前是{task_scope}，目标风格是「{preset.name}」。"
        "无论修改范围是一页还是整份，都要把当前页放在整份 PPT 的连续演讲中理解，不能把每页当成孤立短文。"
        "全局页面脉络如下：\n"
        + "\n".join(outline)
    )
    return DeckNarrativePlan(overview=overview, slide_roles=slide_roles)


def _deck_context(
    plan: DeckNarrativePlan,
    slide,
    position: int,
    total: int,
    memory_context: str,
    language_context: str = "",
) -> str:
    role = plan.slide_roles.get(slide.id, "内容页：承接前后页面，生成自然讲稿。")
    language_line = f"\n语言要求：{language_context}" if language_context else ""
    if total <= 1:
        return (
            f"{plan.overview}\n\n"
            f"当前只修改第 {slide.index} 页，当前页角色：{role}\n"
            "如果当前页不是整份 PPT 的第一页，不要写成全新开场；要像同一场演讲中的中间页一样自然承接。\n"
            f"{language_line}\n"
            f"\n持久化记忆：\n{memory_context}"
        )

    transition_rule = (
        "硬性规则：只有整份任务的第一页可以使用完整问候或开场白；"
        "第 2 页及之后必须直接进入内容或用一句自然转场承接上一页，"
        "不要重复“小朋友们好呀”“大家好”“今天给大家介绍”这类开场。"
    )
    return (
        f"{plan.overview}\n\n"
        f"当前正在写第 {position}/{total} 个目标页面，对应 PPT 第 {slide.index} 页。\n"
        f"当前页角色：{role}\n"
        f"{transition_rule}\n"
        "讲稿需要像同一位讲者连续讲完整份 PPT，避免每页重复同一种句式。"
        f"{language_line}"
        f"\n\n持久化记忆：\n{memory_context}"
    )


def _compact_text(text: str, limit: int = 120) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


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
