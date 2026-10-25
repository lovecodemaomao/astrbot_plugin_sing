"""把「风格」「音色」拼成阶跃音乐模型需要的 caption。"""

from __future__ import annotations

__all__ = ["DEFAULT_STYLE", "VOICE_PRESETS", "build_caption", "describe_voice"]

DEFAULT_STYLE = "轻快 city pop，女声，温暖治愈，中速，清澈"

VOICE_PRESETS: dict[str, str] = {
    "少女": "年轻的少女音，清亮甜美",
    "御姐": "成熟御姐音，低沉有磁性",
    "少年": "干净少年音，略带沙哑",
    "大叔": "低沉大叔音，厚实温暖",
    "清冷": "清冷空灵的女声，气息感强",
    "沙哑": "略带沙哑的烟嗓",
    "童声": "童声，稚嫩活泼",
    "萝莉": "元气萝莉音，软糯可爱",
}


def describe_voice(voice: str) -> str:
    """把音色关键词翻译成模型能理解的描述；未命中的词原样保留。"""
    voice = (voice or "").strip()
    if not voice:
        return ""
    for key, description in VOICE_PRESETS.items():
        if key in voice:
            return description
    return voice


def build_caption(style: str = "", voice: str = "", default_style: str = DEFAULT_STYLE) -> str:
    """组合最终 caption；空风格回退到默认值。"""
    parts: list[str] = []
    base = (style or "").strip() or (default_style or DEFAULT_STYLE).strip()
    if base:
        parts.append(base)
    voice_desc = describe_voice(voice)
    if voice_desc:
        parts.append(voice_desc)
    return "，".join(parts)
