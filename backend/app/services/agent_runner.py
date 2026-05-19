import json
import re
import uuid
from collections.abc import Generator
from dataclasses import dataclass

from app.models.deck import AgentRunCreate, AgentStylePreset
from app.services.ark_client import generate_note
from app.services.memory_store import build_memory_context, record_agent_note_change, record_user_intent
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

        instruction = _resolve_effective_instruction(payload.instruction, payload.messages)
        if _needs_language_clarification(instruction):
            yield _event(
                "assistant",
                {
                    "text": "",
                    "message": "我需要先确认讲稿语言：这次面向外宾，是要中文讲稿、英文讲稿，还是其他语言？你可以回复“中文”“英文”“日文”“泰文”等。",
                    "actions": [],
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
                },
            )
            yield _event("done", {"deck": deck.model_dump()})
            return
        target_slides = _resolve_target_slides(deck.slides, payload.slide_id, deck_scope)
        if not target_slides:
            yield _event("error", {"message": "Slide not found"})
            return
        scope_label = "整份演示文稿" if deck_scope else f"第 {target_slides[0].index} 页"
        yield _event("progress", {"message": f"已识别任务范围：{scope_label}。"})

        preset = _resolve_style_preset(payload.style_preset, instruction, payload.messages)
        yield _event("progress", {"message": f"已应用风格：{preset.name}。"})
        language_context = _language_context(instruction)
        language_label = _language_label(instruction)
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
    user_messages = [
        item.content.strip()
        for item in messages
        if item.role == "user" and item.content and item.content.strip()
    ]
    if user_messages and user_messages[-1] == instruction.strip():
        previous = user_messages[:-1]
    else:
        previous = user_messages

    if not (_is_scope_answer(instruction) or _is_language_answer(instruction)):
        return instruction

    intent = _last_substantive_user_intent(previous)
    if not intent:
        return instruction

    supplements = _recent_supplements_after_intent(previous, intent)
    supplements.append(instruction.strip())
    supplement_text = "\n".join(f"用户补充：{item}" for item in supplements)
    return f"{intent}\n{supplement_text}"


def _last_substantive_user_intent(messages: list[str]) -> str:
    for item in reversed(messages):
        if not _is_scope_answer(item) and not _is_language_answer(item):
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
        if seen_intent and (_is_scope_answer(item) or _is_language_answer(item)):
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
            r"(中文|汉语|普通话|英文|英语|english|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish)",
            normalized,
        )
        or re.fullmatch(
            r"(用|改成|换成)?(中文|汉语|普通话|英文|英语|english|日文|日语|japanese|泰文|泰语|thai|韩文|韩语|korean|法文|法语|french|德文|德语|german|西班牙文|西班牙语|spanish)(讲稿|版本)?",
            normalized,
        )
    )


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
    if _mentions_middle_east(instruction) and not re.search(r"阿拉伯文|阿拉伯语|arabic", instruction, re.IGNORECASE):
        return "目标语言：阿拉伯语。用户提到中东客户时，默认生成阿拉伯语讲稿。content 字段必须使用阿拉伯语，不要输出中文讲稿。"
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
    return ""


def _language_label(instruction: str) -> str:
    if _mentions_middle_east(instruction) or re.search(r"阿拉伯文|阿拉伯语|arabic", instruction, re.IGNORECASE):
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
