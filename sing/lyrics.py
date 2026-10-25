"""歌词生成与清洗。

真正的模型调用通过传入的 provider 完成，保证模块本身可单测。
"""

from __future__ import annotations

import uuid

__all__ = ["FALLBACK_LYRICS", "SYSTEM_PROMPT", "clean_lyrics", "generate_lyrics"]

SYSTEM_PROMPT = (
    "你是一位中文流行歌曲作词人。请为给定的主题写一段适合演唱的短歌词。\n"
    "硬性要求：\n"
    "1. 只输出歌词本身，不要解释、标题、序号说明或 markdown 代码块；\n"
    "2. 必须使用结构标签，标签独占一行，例如 [Verse 1]、[Chorus 1]；\n"
    "3. 总长度 10 到 16 行，句子短、有画面感、押韵自然；\n"
    "4. 不要抄袭任何已有歌曲，不要出现真实歌名、歌手名或品牌名。"
)

FALLBACK_LYRICS = (
    "[Verse 1]\n窗外的风轻轻吹过\n把心事都吹成泡沫\n\n[Chorus 1]\n唱一句 再唱一句\n让歌声替我说\n"
)

_MIN_LYRICS_CHARS = 20


def clean_lyrics(text: str) -> str:
    """去掉代码块包裹与多余空行，保留结构标签。"""
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if "\n" in value:
            value = value.split("\n", 1)[-1]
    lines = [line.rstrip() for line in value.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if not line.strip() and (not cleaned or not cleaned[-1].strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


async def generate_lyrics(
    provider,
    topic: str,
    *,
    persona: str = "",
    extra_hint: str = "",
    max_chars: int = 1500,
) -> str:
    """调用对话模型写词；失败或内容太短时回退到内置示例歌词。"""
    if provider is None:
        return FALLBACK_LYRICS

    prompt_parts = [f"主题：{(topic or '').strip() or '随便写一首轻快的小歌'}"]
    if persona.strip():
        prompt_parts.append(f"角色人设：{persona.strip()}")
    if extra_hint.strip():
        prompt_parts.append(f"额外要求：{extra_hint.strip()}")
    prompt_parts.append("请按系统要求输出歌词。")

    try:
        response = await provider.text_chat(
            prompt="\n".join(prompt_parts),
            system_prompt=SYSTEM_PROMPT,
            session_id=str(uuid.uuid4()),
        )
    except Exception:
        return FALLBACK_LYRICS

    lyrics = clean_lyrics(getattr(response, "completion_text", "") or "")
    if len(lyrics) < _MIN_LYRICS_CHARS:
        return FALLBACK_LYRICS
    return lyrics[:max_chars]
