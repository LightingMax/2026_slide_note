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
        message = str(payload.get("message") or "已生成备注草稿。")
        actions = []
        for item in payload.get("actions", []):
            if item.get("type") != "replace_notes":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            actions.append(
                AgentAction(
                    type="replace_notes",
                    slide_id=str(item.get("slide_id") or slide_id),
                    label=str(item.get("label") or "替换当前页备注"),
                    content=content,
                )
            )
        if actions:
            return ChatResponse(text=actions[0].content, message=message, actions=actions)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    fallback = raw_text.strip()
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


def _extract_json(raw_text: str) -> str:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text
