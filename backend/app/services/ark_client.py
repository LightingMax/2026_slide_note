import json
import re

from openai import APIError, AuthenticationError, OpenAI

from app.core.config import get_settings
from app.models.deck import AgentAction, ChatResponse, Slide


def resolve_task_instruction(
    instruction: str,
    history: list[dict[str, str]],
    fallback_instruction: str,
    deck_filename: str,
    slide_count: int,
) -> str:
    settings = get_settings()
    if not settings.ark_api_key:
        return fallback_instruction

    client = OpenAI(base_url=settings.ark_base_url, api_key=settings.ark_api_key)
    safe_history = [
        {"role": item["role"], "content": item["content"]}
        for item in history[-12:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    prompt = (
        "你是 Slide Note 的意图解析器，只负责理解用户当前这句话和最近会话的关系，不生成讲稿。"
        "请判断当前输入是新任务、对上一份计划的补充/修订、回答澄清问题，还是确认执行。"
        "你必须只输出 JSON，不要输出 Markdown。JSON 格式："
        '{"relation":"new_task|revise_previous_plan|answer_clarification|confirm_plan",'
        '"confidence":0.0,'
        '"normalized_instruction":"规整后的完整任务指令，必须包含应继承的原始任务、用户补充、用户确认"}。'
        "规整规则："
        "如果用户说“可以、好的、按这个来、确认”等，且上一轮 assistant 给过执行计划，应作为 confirm_plan，并在 normalized_instruction 里保留原任务和补充，同时追加“用户确认：确认执行”。"
        "如果用户说“哦不对、通知说、其实、改成、换成”等，应作为 revise_previous_plan，继承上一份计划的范围、受众、文件和任务，只覆盖用户明确修改的字段。"
        "如果用户回答语言、范围或风格澄清，应作为 answer_clarification，继承原任务并追加补充。"
        "如果确实与上一份计划无关，才作为 new_task。"
        "不要虚构用户没有说过的语言或范围；但可以保留上一轮计划中已经确定的信息。"
        f"\n\n当前文件：{deck_filename}，共 {slide_count} 页。"
        f"\n当前用户输入：{instruction}"
    )
    messages = [
        {"role": "system", "content": "你是严格 JSON 意图解析器。"},
        *safe_history,
        {"role": "user", "content": prompt},
    ]

    try:
        response = client.responses.create(model=settings.ark_model, input=messages)
    except (AuthenticationError, APIError):
        return fallback_instruction

    raw_text = getattr(response, "output_text", "") or str(response)
    try:
        payload = json.loads(_extract_json(raw_text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback_instruction

    relation = str(payload.get("relation") or "")
    normalized = str(payload.get("normalized_instruction") or "").strip()
    confidence = _safe_float(payload.get("confidence"), 0.0)
    if relation not in {"new_task", "revise_previous_plan", "answer_clarification", "confirm_plan"}:
        return fallback_instruction
    if confidence < 0.55 or not normalized:
        return fallback_instruction
    return normalized


def generate_note(
    slide: Slide,
    instruction: str,
    history: list[dict[str, str]],
    style_instruction: str = "",
    deck_context: str = "",
) -> ChatResponse:
    settings = get_settings()
    if not settings.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured")

    client = OpenAI(base_url=settings.ark_base_url, api_key=settings.ark_api_key)
    prompt = (
        "你是 Slide Note 的智能备注编辑 agent。请基于幻灯片内容生成一个可执行响应。"
        f"本次唯一可信的当前页是：第 {slide.index} 页，slide_id={slide.id}。"
        "历史消息里出现的其他页码、页 ID 或上一次处理结果，都不能作为本次目标页。"
        "你必须只输出 JSON，不要输出 Markdown。JSON 格式："
        '{"message":"给用户看的简短说明","actions":[{"type":"replace_notes","slide_id":"'
        f'{slide.id}","label":"替换当前页备注","content":"可直接放入备注区的目标语言播报稿"}}]}}。'
        f"actions[0].slide_id 必须严格等于 {slide.id}。"
        "content 必须使用叙事约束中指定的目标语言，适合语音播报：自然、清晰、短句、不要使用项目符号堆砌。"
        "content 必须是最终可直接朗读版本，禁止出现占位符、二选一表达、斜杠候选、括号候选、变量提示或待替换文本。"
        "例如不要写 Good morning/afternoon、各位来宾（或客户）、[公司名]、{时间}、请根据现场调整。"
        f"\n\n风格要求：\n{style_instruction or '自然口语化讲稿风格'}"
        f"\n\n整份 PPT 叙事约束：\n{deck_context or '这是单页任务，围绕当前页内容生成讲稿。'}"
        "\n\n幻灯片标题："
        f"{slide.title}\n\n幻灯片文字：\n{slide.text or '无'}\n\n当前备注：\n{slide.notes or '无'}"
        f"\n\n用户要求：{instruction}"
    )

    messages = [
        {
            "role": "system",
            "content": "你是可执行 agent，只返回 JSON。支持的 action 只有 replace_notes。当前页信息只以最后一条用户消息中的任务 prompt 为准。",
        }
    ]
    safe_history = [
        {"role": item["role"], "content": item["content"]}
        for item in history[-8:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    messages.extend(safe_history)
    messages.append({"role": "user", "content": prompt})

    try:
        response = client.responses.create(model=settings.ark_model, input=messages)
    except AuthenticationError as exc:
        raise RuntimeError("ARK_API_KEY 无效或未授权，请检查火山方舟控制台中的 API Key。") from exc
    except APIError as exc:
        raise RuntimeError(f"模型服务请求失败：{exc.message}") from exc
    raw_text = getattr(response, "output_text", "") or str(response)
    return _parse_agent_response(raw_text, slide.id)


def _parse_agent_response(raw_text: str, slide_id: str) -> ChatResponse:
    try:
        payload = json.loads(_extract_json(raw_text))
        response = _response_from_payload(payload, slide_id)
        if response.actions:
            return response
    except (json.JSONDecodeError, TypeError, ValueError):
        repaired = _parse_loose_json_response(raw_text, slide_id)
        if repaired.actions:
            return repaired

    fallback = _extract_loose_content(raw_text).strip()
    return ChatResponse(
        text=fallback,
        message="已生成备注草稿。",
        actions=[
            AgentAction(
                type="replace_notes",
                slide_id=slide_id,
                label="替换当前页备注",
                content=fallback,
            )
        ],
    )


def _response_from_payload(payload: dict, slide_id: str) -> ChatResponse:
    message = str(payload.get("message") or "已生成备注草稿。")
    actions = []
    for item in payload.get("actions", []):
        if item.get("type") != "replace_notes":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        content = _extract_loose_content(content).strip()
        content = _sanitize_speech_content(content)
        actions.append(
            AgentAction(
                type="replace_notes",
                slide_id=str(item.get("slide_id") or slide_id),
                label=str(item.get("label") or "替换当前页备注"),
                content=content,
            )
        )
    return ChatResponse(text=actions[0].content if actions else "", message=message, actions=actions)


def _parse_loose_json_response(raw_text: str, slide_id: str) -> ChatResponse:
    text = _extract_json(raw_text)
    message_match = re.search(r'"message"\s*:\s*"(?P<message>.*?)"\s*,\s*"actions"', text, re.DOTALL)
    content = _extract_loose_content(text).strip()
    if not content or content == text.strip():
        return ChatResponse(text="", message="", actions=[])
    message = message_match.group("message") if message_match else "已生成备注草稿。"
    return ChatResponse(
        text=content,
        message=message,
        actions=[
            AgentAction(
                type="replace_notes",
                slide_id=slide_id,
                label="替换当前页备注",
                content=content,
            )
        ],
    )


def _extract_loose_content(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text
    try:
        payload = json.loads(stripped)
        actions = payload.get("actions", [])
        if actions and isinstance(actions, list):
            content = actions[0].get("content", "")
            if content:
                return str(content)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    marker = '"content"'
    start = stripped.find(marker)
    if start < 0:
        return text
    colon = stripped.find(":", start + len(marker))
    if colon < 0:
        return text
    first_quote = stripped.find('"', colon + 1)
    if first_quote < 0:
        return text
    end_markers = ['"}]}', '"}]}', '"}] }', '"}\n]}']
    end = -1
    for marker in end_markers:
        candidate = stripped.rfind(marker)
        if candidate > first_quote:
            end = candidate
            break
    if end < 0:
        end = stripped.rfind('"')
    if end <= first_quote:
        return text
    return stripped[first_quote + 1 : end].replace('\\"', '"')


def _sanitize_speech_content(content: str) -> str:
    replacements = [
        (r"Good morning/afternoon,?\s*", "Good morning, "),
        (r"good morning/afternoon,?\s*", "Good morning, "),
        (r"早上好/下午好，?", "大家好，"),
        (r"上午好/下午好，?", "大家好，"),
    ]
    cleaned = content
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned)
    cleaned = re.sub(r"\[(?:[^\[\]]{1,30})\]", "", cleaned)
    cleaned = re.sub(r"\{(?:[^{}]{1,30})\}", "", cleaned)
    cleaned = re.sub(r"（或[^）]{1,20}）", "", cleaned)
    cleaned = re.sub(r"\(or [^)]{1,30}\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bWelcome to\s*[.。]", "Welcome.", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _safe_float(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _extract_json(raw_text: str) -> str:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text
