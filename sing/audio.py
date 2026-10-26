"""参考音频处理：从消息里取出音频、下载 URL、校验大小与时长、转 base64。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "AUDIO_EXTS",
    "AudioError",
    "encode_base64",
    "probe_duration",
    "resolve_reference",
    "split_for_qq",
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
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".flv"}
VIDEO_HOSTS = {"bilibili.com", "b23.tv", "youtube.com", "youtu.be"}


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


def _video_site(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and (port is None or port in {80, 443})
        and any(host == domain or host.endswith("." + domain) for domain in VIDEO_HOSTS)
    )


async def _download_video(url: str, target_dir: Path, max_seconds: float) -> Path:
    """提取公开视频音轨；限制站点、时长和下载文件大小。"""
    if not _video_site(url):
        raise AudioError("暂只支持 B 站、YouTube 的公开视频链接")
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = f"ref_{uuid.uuid4().hex[:8]}"
    output = target_dir / f"{stem}.%(ext)s"
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--max-filesize",
        "50M",
        "--match-filter",
        f"duration <= {int(max_seconds)}",
        "-f",
        "bestaudio/best",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "128K",
        "-o",
        str(output),
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AudioError("视频音轨提取工具不可用") from exc
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=240)
    except TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise AudioError("下载视频音轨超时") from exc
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise AudioError(f"提取视频音轨失败：{detail[0][:180]}")
    result = target_dir / f"{stem}.mp3"
    if not result.is_file():
        raise AudioError("视频音轨下载后未找到 MP3 文件")
    return result


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
    event,
    *,
    url: str = "",
    work_dir: Path,
    max_mb: float = 20.0,
    max_seconds: float = 360.0,
) -> tuple[Path, str]:
    """按优先级取参考音频：命令里的 URL > 当前消息附件 > 引用消息附件。

    Returns:
        (本地文件路径, 来源说明)

    Raises:
        AudioError: 没有音频、下载失败或超过大小限制。
    """
    if url:
        if _video_site(url):
            path = await _download_video(url, work_dir, max_seconds)
            return _check_size(path, max_mb), "视频链接"
        path = await _download(url, work_dir, max_mb)
        return _check_size(path, max_mb), "链接"

    from astrbot.core.message.components import File, Record, Reply, Video

    messages = list(event.get_messages())

    def _audio_components(components):
        for comp in components or []:
            if isinstance(comp, (Record, File, Video)):
                yield comp
            elif isinstance(comp, Reply):
                for nested in getattr(comp, "chain", None) or []:
                    if isinstance(nested, (Record, File, Video)):
                        yield nested

    for comp in _audio_components(messages):
        if isinstance(comp, Video):
            try:
                path = Path(await comp.convert_to_file_path())
            except Exception as exc:
                raise AudioError(f"读取视频失败：{exc}") from exc
            return await _prepare_local(path, work_dir, max_mb), "视频消息"
        if isinstance(comp, Record):
            try:
                path = Path(await comp.convert_to_file_path())
            except Exception as exc:
                raise AudioError(f"读取语音失败：{exc}") from exc
            return await _prepare_local(path, work_dir, max_mb), "语音消息"
        if isinstance(comp, File):
            try:
                raw = await comp.get_file()
            except Exception as exc:
                raise AudioError(f"读取音频文件失败：{exc}") from exc
            path = Path(str(raw))
            if not path.is_absolute():
                raise AudioError("音频文件路径无效")
            return await _prepare_local(path, work_dir, max_mb), "音频文件"

    raise AudioError("没找到参考音频，请把歌曲或语音和命令一起发，或者引用那条消息")


async def _prepare_local(path: Path, work_dir: Path, max_mb: float) -> Path:
    """视频提取音轨；QQ 转成过大 WAV 时压回 MP3。"""
    if not path.is_file():
        raise AudioError("参考音频文件不存在")
    is_video = path.suffix.lower() in VIDEO_EXTS
    if not is_video and path.stat().st_size <= max_mb * 1024 * 1024:
        return path

    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"ref_{uuid.uuid4().hex[:8]}.mp3"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-map_metadata",
            "-1",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k" if is_video else "192k",
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise AudioError("压缩参考音频超时") from exc
        if proc.returncode != 0:
            raise AudioError(f"压缩参考音频失败：{stderr.decode(errors='replace')[:160]}")
        return _check_size(target, max_mb)
    except FileNotFoundError as exc:
        raise AudioError("参考音频过大，且服务器未安装 FFmpeg") from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise


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


async def split_for_qq(path: Path, work_dir: Path, max_seconds: float = 55.0) -> list[Path]:
    """QQ 官方通道对长语音不稳定，拆成短 MP3 后按顺序发送。"""
    duration = probe_duration(path)
    if not duration or duration <= max_seconds:
        return [path]
    work_dir.mkdir(parents=True, exist_ok=True)
    pattern = work_dir / f"{path.stem}_part_%02d.mp3"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-c:a",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(max_seconds),
            str(pattern),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise AudioError("拆分语音超时") from exc
        if proc.returncode != 0:
            raise AudioError(f"FFmpeg 拆分失败：{stderr.decode(errors='replace')[:160]}")
    except FileNotFoundError as exc:
        raise AudioError("服务器没有 FFmpeg，无法拆分长语音") from exc
    parts = sorted(work_dir.glob(f"{path.stem}_part_*.mp3"))
    if not parts or any(part.stat().st_size == 0 for part in parts):
        raise AudioError("拆分后没有得到有效语音")
    return parts


def encode_base64(path: Path) -> bytes:
    """返回音频原始字节（由客户端负责 base64 编码）。"""
    return path.read_bytes()
