import json
import re

from openai import APIError, AuthenticationError, OpenAI

from app.core.config import get_settings
from app.models.deck import AgentAction, ChatResponse, Slide


def generate_note(
    slide: Slide,
    instruction: str,
    history: list[dict[str, str]],
    style_instruction: str = "",
) -> ChatResponse:
    settings = get_settings()
    if not settings.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured")

    client = OpenAI(base_url=settings.ark_base_url, api_key=settings.ark_api_key)
    prompt = (
        "你是 Slide Note 的智能备注编辑 agent。请基于幻灯片内容生成一个可执行响应。"
        "你必须只输出 JSON，不要输出 Markdown。JSON 格式："
        '{"message":"给用户看的简短说明","actions":[{"type":"replace_notes","slide_id":"'
        f'{slide.id}","label":"替换当前页备注","content":"可直接放入备注区的中文播报稿"}}]}}。'
        "content 要适合语音播报：自然、清晰、短句、不要使用项目符号堆砌。"
        f"\n\n风格要求：\n{style_instruction or '自然口语化讲稿风格'}"
        "\n\n幻灯片标题："
        f"{slide.title}\n\n幻灯片文字：\n{slide.text or '无'}\n\n当前备注：\n{slide.notes or '无'}"
        f"\n\n用户要求：{instruction}"
    )

    messages = [
        {
            "role": "system",
            "content": "你是可执行 agent，只返回 JSON。支持的 action 只有 replace_notes。",
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


def _extract_json(raw_text: str) -> str:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text
