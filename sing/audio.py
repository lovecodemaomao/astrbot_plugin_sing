"""参考音频处理：从消息里取出音频、下载 URL、校验大小与时长、转 base64。"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "AUDIO_EXTS",
    "AudioError",
    "encode_base64",
    "probe_duration",
    "resolve_reference",
    "validate",
]

AUDIO_EXTS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".flac",
    ".amr",
    ".silk",
    ".aac",
    ".opus",
    ".weba",
}


class AudioError(RuntimeError):
    """参考音频不可用。"""


def _suffix_of(path: str) -> str:
    suffix = Path(urlsplit(str(path)).path).suffix.lower()
    return suffix if suffix in AUDIO_EXTS else ".mp3"


def _public_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def _download(url: str, target_dir: Path, max_mb: float, timeout: float = 120.0) -> Path:
    import aiohttp

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise AudioError("音频链接必须是公开的 HTTP(S) 地址")

    class PublicResolver(aiohttp.abc.AbstractResolver):
        def __init__(self):
            self._resolver = aiohttp.resolver.DefaultResolver()

        async def resolve(self, host, port=0, family=socket.AF_INET):
            addresses = await self._resolver.resolve(host, port, family)
            if not addresses or any(not _public_address(item["host"]) for item in addresses):
                raise AudioError("音频链接指向了非公开网络地址")
            return addresses

        async def close(self):
            await self._resolver.close()

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ref_{uuid.uuid4().hex[:8]}{_suffix_of(url)}"
    limit = int(max_mb * 1024 * 1024)
    try:
        connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
        async with (
            aiohttp.ClientSession(
                connector=connector, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session,
            session.get(url, allow_redirects=False) as response,
        ):
            if response.status != 200:
                raise AudioError(f"下载参考音频失败（HTTP {response.status}）")
            if response.content_length is not None and response.content_length > limit:
                raise AudioError("参考音频超过大小上限")
            size = 0
            with target.open("wb") as output:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise AudioError("参考音频超过大小上限")
                    output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


async def resolve_reference(
    event, *, url: str = "", work_dir: Path, max_mb: float = 20.0
) -> tuple[Path, str]:
    """按优先级取参考音频：命令里的 URL > 当前消息附件 > 引用消息附件。

    Returns:
        (本地文件路径, 来源说明)

    Raises:
        AudioError: 没有音频、下载失败或超过大小限制。
    """
    if url:
        path = await _download(url, work_dir, max_mb)
        return _check_size(path, max_mb), "链接"

    from astrbot.core.message.components import File, Record, Reply

    messages = list(event.get_messages())

    def _audio_components(components):
        for comp in components or []:
            if isinstance(comp, (Record, File)):
                yield comp
            elif isinstance(comp, Reply):
                for nested in getattr(comp, "chain", None) or []:
                    if isinstance(nested, (Record, File)):
                        yield nested

    for comp in _audio_components(messages):
        if isinstance(comp, Record):
            try:
                path = Path(await comp.convert_to_file_path())
            except Exception as exc:
                raise AudioError(f"读取语音失败：{exc}") from exc
            return _check_size(path, max_mb), "语音消息"
        if isinstance(comp, File):
            try:
                raw = comp.file
            except Exception as exc:
                raise AudioError(f"读取音频文件失败：{exc}") from exc
            path = Path(str(raw))
            if not path.is_absolute():
                raise AudioError("音频文件路径无效")
            return _check_size(path, max_mb), "音频文件"

    raise AudioError("没找到参考音频，请把歌曲或语音和命令一起发，或者引用那条消息")


def _check_size(path: Path, max_mb: float) -> Path:
    if not path.is_file():
        raise AudioError("参考音频文件不存在")
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        raise AudioError(f"参考音频太大（{size_mb:.1f}MB > {max_mb:g}MB）")
    return path


def probe_duration(path: Path) -> float:
    """用 ffprobe 读时长（秒）；失败返回 0 表示未知。"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def validate(path: Path, *, max_mb: float = 20.0, max_seconds: float = 360.0) -> float:
    """校验大小与时长，返回时长（未知为 0）。"""
    _check_size(path, max_mb)
    duration = probe_duration(path)
    if duration and duration > max_seconds:
        raise AudioError(f"参考音频太长（{duration:.0f} 秒 > {max_seconds:.0f} 秒）")
    return duration


def encode_base64(path: Path) -> bytes:
    """返回音频原始字节（由客户端负责 base64 编码）。"""
    return path.read_bytes()
