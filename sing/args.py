"""参数解析：把 /唱歌、/翻唱 后面的自由文本与 --flag 解析成结构化选项。

这个模块不依赖 AstrBot，便于单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ArgsError", "CommandOptions", "parse", "tokenize"]


class ArgsError(ValueError):
    """用户传入了非法的参数组合。"""


@dataclass
class CommandOptions:
    """一次点歌请求的解析结果。"""

    text: str = ""
    style: str = ""
    voice: str = ""
    lyrics: str = ""
    audio_url: str = ""
    instrumental: bool = False
    dry_vocal: bool = False
    want_help: bool = False


_VALUE_FLAGS = {
    "--风格": "style",
    "--style": "style",
    "--音色": "voice",
    "--voice": "voice",
    "--歌词": "lyrics",
    "--lyrics": "lyrics",
    "--音频": "audio_url",
    "--视频": "audio_url",
    "--audio": "audio_url",
    "--video": "audio_url",
    "--url": "audio_url",
}

_BOOL_FLAGS = {
    "--纯音乐": "instrumental",
    "--instrumental": "instrumental",
    "--bgm": "instrumental",
    "--干声": "dry_vocal",
    "--dry": "dry_vocal",
}

_HELP_FLAGS = {"-h", "--help", "--帮助", "--用法"}


def tokenize(raw: str) -> list[str]:
    """按空白切分，支持用双引号或单引号包住带空格的值。"""
    tokens: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in raw or "":
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
            continue
        if ch in "'\"":
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def parse(raw: str, *, mode: str = "sing") -> CommandOptions:
    """解析命令参数。

    Args:
        raw: 命令后面的原始文本。
        mode: ``sing``（原唱）或 ``cover``（翻唱），用于校验互斥参数。

    Returns:
        解析后的 :class:`CommandOptions`。

    Raises:
        ArgsError: 参数缺失、未知参数或组合非法。
    """
    if mode not in {"sing", "cover"}:
        raise ArgsError(f"未知模式：{mode}")

    opts = CommandOptions()
    tokens = tokenize(raw)
    words: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token in _HELP_FLAGS:
            opts.want_help = True
            index += 1
            continue

        if token in _BOOL_FLAGS:
            setattr(opts, _BOOL_FLAGS[token], True)
            index += 1
            continue

        name, has_eq, inline = token.partition("=")
        if name in _VALUE_FLAGS:
            if has_eq:
                value = inline
            else:
                if index + 1 >= len(tokens):
                    raise ArgsError(f"参数 {token} 需要一个值")
                value = tokens[index + 1]
                index += 1
            setattr(opts, _VALUE_FLAGS[name], value.strip())
            index += 1
            continue

        if token.startswith("-") and len(token) > 1:
            raise ArgsError(f"不认识的参数：{token}")

        if mode == "cover" and token.startswith(("https://", "http://")) and not opts.audio_url:
            opts.audio_url = token
        else:
            words.append(token)
        index += 1

    opts.text = " ".join(words).strip()
    _validate(opts, mode)
    return opts


def _validate(opts: CommandOptions, mode: str) -> None:
    if mode == "sing":
        if opts.dry_vocal:
            raise ArgsError("--干声 只能用在 /翻唱 上")
        if opts.audio_url:
            raise ArgsError("--音频 只能用在 /翻唱 上")
        if opts.instrumental and opts.lyrics:
            raise ArgsError("--纯音乐 不能和 --歌词 同时使用")
        return

    if opts.instrumental:
        raise ArgsError("--纯音乐 只能用在 /唱歌 上")
