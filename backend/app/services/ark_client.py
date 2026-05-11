from openai import OpenAI

from app.core.config import get_settings
from app.models.deck import Slide


def generate_note(slide: Slide, instruction: str, history: list[dict[str, str]]) -> str:
    settings = get_settings()
    if not settings.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured")

    client = OpenAI(base_url=settings.ark_base_url, api_key=settings.ark_api_key)
    prompt = (
        "你是 Slide Note 的演讲备注编辑助手。请基于幻灯片内容改写备注，"
        "文本要适合语音播报：自然、清晰、短句、不要使用项目符号堆砌。"
        "\n\n幻灯片标题："
        f"{slide.title}\n\n幻灯片文字：\n{slide.text or '无'}\n\n当前备注：\n{slide.notes or '无'}"
        f"\n\n用户要求：{instruction}"
    )

    messages = [{"role": "system", "content": "你只输出可直接放入备注区的中文播报稿。"}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": prompt})

    response = client.responses.create(model=settings.ark_model, input=messages)
    return getattr(response, "output_text", "") or str(response)

