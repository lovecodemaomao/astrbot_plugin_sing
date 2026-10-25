"""阶跃星辰语音识别（用于翻唱时从参考音频里听出歌词）。"""

from __future__ import annotations

import json
from pathlib import Path

import aiohttp

__all__ = ["AsrError", "transcribe"]

DEFAULT_ASR_URL = "https://api.stepfun.com/v1/audio/transcriptions"
DEFAULT_ASR_MODEL = "stepaudio-2.5-asr"


class AsrError(RuntimeError):
    """语音识别失败。"""


async def transcribe(
    api_key: str,
    audio_path: Path | str,
    *,
    model: str = DEFAULT_ASR_MODEL,
    url: str = DEFAULT_ASR_URL,
    timeout: float = 120.0,
    session_factory=None,
) -> str:
    """返回识别出的文本；失败抛 :class:`AsrError`。"""
    path = Path(audio_path)
    if not path.is_file():
        raise AsrError("参考音频不存在")

    data = aiohttp.FormData()
    data.add_field("model", model or DEFAULT_ASR_MODEL)
    data.add_field("response_format", "json")
    data.add_field(
        "file",
        path.read_bytes(),
        filename=path.name,
        content_type="application/octet-stream",
    )
    headers = {"Authorization": f"Bearer {(api_key or '').strip()}"}

    if session_factory is not None:
        session_cm = session_factory()
    else:
        session_cm = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))

    async with (
        session_cm as session,
        session.post(url, data=data, headers=headers) as response,
    ):
        status = response.status
        body = await response.text()

    if status >= 400:
        raise AsrError(f"语音识别失败（HTTP {status}）：{body[:160]}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AsrError("语音识别返回了无法解析的内容") from exc

    text = str(payload.get("text") or "").strip()
    if not text:
        raise AsrError("语音识别没有返回文字")
    return text
