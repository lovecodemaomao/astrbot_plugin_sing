"""astrbot_plugin_sing：用阶跃星辰 StepAudio 3 Music 唱歌与翻唱。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import File, Record
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from .sing import args, audio, caption, lyrics, quota
from .sing.api import MusicApiError, StepFunMusicClient
from .sing.asr import AsrError, transcribe

PLUGIN_NAME = "astrbot_plugin_sing"
PLUGIN_VERSION = "1.0.0"

HELP_SING = (
    "用法：/唱歌 [主题] [--风格 描述] [--音色 预设] [--歌词 歌词] [--纯音乐]\n"
    "例：/唱歌 夏天的海 --音色 少女 --风格 轻快 city pop"
)
HELP_COVER = (
    "用法：/翻唱 [--风格 描述] [--音色 预设] [--歌词 歌词] [--干声] [--音频 URL]\n"
    "把歌曲文件/语音和命令一起发，或引用那条消息；--干声 会保留参考音频的音色"
)


@register(
    PLUGIN_NAME,
    "lovecodemaomao",
    "用阶跃星辰 StepAudio 3 Music 生成带人声的原创歌曲，支持翻唱",
    PLUGIN_VERSION,
)
class SingPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        cfg = config or {}
        self.api_key = str(cfg.get("api_key") or "").strip()
        self.model_id = str(cfg.get("model_id") or "stepaudio-3-music-preview").strip()
        self.asr_model = str(cfg.get("asr_model") or "stepaudio-2.5-asr").strip()
        self.default_style = str(cfg.get("default_style") or caption.DEFAULT_STYLE).strip()
        self.persona = str(cfg.get("persona_prompt") or "").strip()
        self.daily_limit = max(1, int(cfg.get("daily_limit") or 5))
        self.poll_interval = max(3, int(cfg.get("poll_interval") or 8))
        self.max_wait = max(60, int(cfg.get("max_wait_seconds") or 480))
        self.max_ref_mb = max(1, int(cfg.get("max_ref_mb") or 20))
        self.max_ref_seconds = max(10, int(cfg.get("max_ref_seconds") or 360))
        self.enable_llm_tools = bool(cfg.get("enable_llm_tools", True))
        self.keep_days = max(1, int(cfg.get("keep_generated_days") or 7))

        self.data_dir = Path("data") / "plugin_data" / PLUGIN_NAME
        self.gen_dir = self.data_dir / "generated"
        self.ref_dir = self.data_dir / "refs"
        self.gen_dir.mkdir(parents=True, exist_ok=True)
        self.ref_dir.mkdir(parents=True, exist_ok=True)

        self._quota = quota.DailyQuota(self.data_dir / "quota.json", self.daily_limit)
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(2)
        self._tasks: set[asyncio.Task] = set()
        self._client = StepFunMusicClient(
            self.api_key,
            model_id=self.model_id,
            poll_interval=self.poll_interval,
            max_wait=self.max_wait,
        )
        self._cleanup_generated()

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------
    @filter.command("唱歌", alias={"sing", "唱"})
    async def cmd_sing(self, event: AstrMessageEvent, raw: GreedyStr = ""):
        """点一首原创歌曲：/唱歌 夏天的海"""
        async for result in self._handle_command(event, str(raw or ""), "sing"):
            yield result

    @filter.command("翻唱", alias={"cover", "翻"})
    async def cmd_cover(self, event: AstrMessageEvent, raw: GreedyStr = ""):
        """翻唱参考音频：/翻唱（配合歌曲文件或语音）"""
        async for result in self._handle_command(event, str(raw or ""), "cover"):
            yield result

    async def _handle_command(self, event: AstrMessageEvent, raw: str, mode: str):
        if not self.api_key:
            yield event.plain_result("还没配置阶跃星辰的 API Key，去 WebUI 插件配置里填一下就能唱了。")
            return

        try:
            options = args.parse(raw, mode=mode)
        except args.ArgsError as exc:
            yield event.plain_result(f"{exc}\n\n{HELP_SING if mode == 'sing' else HELP_COVER}")
            return

        if options.want_help or (
            mode == "sing" and not (options.text or options.lyrics or options.instrumental)
        ):
            yield event.plain_result(HELP_SING if mode == "sing" else HELP_COVER)
            return

        umo = str(event.unified_msg_origin)
        if self._quota.remaining(umo) <= 0:
            yield event.plain_result(f"今天已经唱够 {self.daily_limit} 首啦，明天再来吧～")
            return
        self._quota.consume(umo)

        yield event.plain_result("在写了在写了，大概 1~3 分钟，唱好我直接把语音发出来～")
        self._spawn(self._generate_and_send(event, options, mode))

    # ------------------------------------------------------------------
    # LLM 工具
    # ------------------------------------------------------------------
    @filter.llm_tool(name="sing_song")
    async def tool_sing(self, event: AstrMessageEvent, topic: str = "", style: str = "", voice: str = ""):
        """唱一首原创歌曲并发送语音。用户想听你唱歌、点歌、让你来一段时调用。

        Args:
            topic (string): 想唱的主题或场景，例如「夏天的海」「加班」「白米饭」
            style (string): 曲风描述，可留空
            voice (string): 音色，例如 少女、御姐、少年、大叔，可留空
        """
        return await self._handle_tool(event, "sing", topic=topic, style=style, voice=voice)

    @filter.llm_tool(name="cover_song")
    async def tool_cover(
        self,
        event: AstrMessageEvent,
        style: str = "",
        voice: str = "",
        lyrics: str = "",
    ):
        """翻唱当前消息或引用消息里的歌曲/语音，并发送结果。

        Args:
            style (string): 目标曲风，可留空
            voice (string): 目标音色，可留空
            lyrics (string): 指定歌词，可留空
        """
        return await self._handle_tool(event, "cover", style=style, voice=voice, lyrics=lyrics)

    async def _handle_tool(self, event: AstrMessageEvent, mode: str, **kwargs) -> str:
        if not self.enable_llm_tools:
            return "唱歌工具已被管理员关闭。"
        if not self.api_key:
            return "没有配置阶跃星辰 API Key，唱不了。"

        options = args.CommandOptions(
            text=str(kwargs.get("topic") or ""),
            style=str(kwargs.get("style") or ""),
            voice=str(kwargs.get("voice") or ""),
            lyrics=str(kwargs.get("lyrics") or ""),
        )
        umo = str(event.unified_msg_origin)
        if self._quota.remaining(umo) <= 0:
            return f"今天已经唱够 {self.daily_limit} 首了，明天再唱。"
        self._quota.consume(umo)

        self._spawn(self._generate_and_send(event, options, mode))
        return "已经开始写了，1~3 分钟后会把语音发出来。"

    # ------------------------------------------------------------------
    # 生成与发送
    # ------------------------------------------------------------------
    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _generate_and_send(
        self, event: AstrMessageEvent, options: args.CommandOptions, mode: str
    ) -> None:
        umo = str(event.unified_msg_origin)
        lock = self._locks.setdefault(umo, asyncio.Lock())
        async with lock:
            async with self._semaphore:
                try:
                    path = await self._produce(event, options, mode)
                except (MusicApiError, AsrError, audio.AudioError) as exc:
                    logger.warning("[sing] 生成失败：%s", exc)
                    await self._send_text(umo, f"唱失败了：{exc}")
                    return
                except Exception:
                    logger.exception("[sing] 未预期错误")
                    await self._send_text(umo, "唱的时候出了点意外，稍后再试一次吧。")
                    return
            await self._send_audio(umo, path)
            self._cleanup_generated()

    async def _produce(self, event: AstrMessageEvent, options: args.CommandOptions, mode: str) -> Path:
        style = caption.build_caption(options.style, options.voice, self.default_style)

        if mode == "sing":
            text = options.lyrics.strip()
            if not text and not options.instrumental:
                provider = await self.context.get_using_provider_async(str(event.unified_msg_origin))
                text = await lyrics.generate_lyrics(provider, options.text, persona=self.persona)
            task_id, raw = await self._client.generate(
                caption=style,
                lyrics=None if options.instrumental else text,
                instrumental=options.instrumental,
            )
            return self._save(task_id, raw)

        # 翻唱
        ref_path, source = await audio.resolve_reference(
            event,
            url=options.audio_url,
            work_dir=self.ref_dir,
            max_mb=self.max_ref_mb,
        )
        duration = audio.validate(ref_path, max_mb=self.max_ref_mb, max_seconds=self.max_ref_seconds)
        logger.info("[sing] 参考音频 %s（%s，%.0f 秒）", ref_path.name, source, duration)

        cover_lyrics = options.lyrics.strip()
        if not cover_lyrics:
            try:
                cover_lyrics = await transcribe(self.api_key, ref_path, model=self.asr_model)
            except AsrError as exc:
                logger.warning("[sing] 识别歌词失败：%s", exc)
                raise AsrError("没能从参考音频识别歌词，请用 --歌词 提供这一段歌词") from exc

        audio_bytes = audio.encode_base64(ref_path)
        if options.dry_vocal:
            task_id, raw = await self._client.generate(
                caption=style,
                lyrics=cover_lyrics,
                task="vocal_to_music",
                vocal_audio=audio_bytes,
            )
        else:
            task_id, raw = await self._client.generate(
                caption=style,
                lyrics=cover_lyrics,
                task="music_cover",
                song_audio=audio_bytes,
            )
        return self._save(task_id, raw)

    def _save(self, task_id: str, raw: bytes) -> Path:
        path = self.gen_dir / f"sing_{task_id[:8]}.mp3"
        path.write_bytes(raw)
        logger.info("[sing] 已保存 %s（%d 字节）", path, len(raw))
        return path

    async def _send_audio(self, umo: str, path: Path) -> None:
        try:
            await self.context.send_message(umo, MessageChain([Record.fromFileSystem(str(path))]))
            return
        except Exception as exc:
            logger.warning("[sing] 语音发送失败，改用文件：%s", exc)
        try:
            await self.context.send_message(
                umo,
                MessageChain([File(name=path.name, file=str(path))]),
            )
        except Exception as exc:
            logger.error("[sing] 文件发送也失败：%s", exc)
            await self._send_text(umo, "歌生成好了，但 QQ 没有接受语音或文件。请联系管理员查看日志。")

    async def _send_text(self, umo: str, text: str) -> None:
        try:
            await self.context.send_message(umo, MessageChain().message(text))
        except Exception as exc:
            logger.error("[sing] 文本发送失败：%s", exc)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def _cleanup_generated(self) -> None:
        cutoff = time.time() - self.keep_days * 86400
        for path in self.gen_dir.glob("*.mp3"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
        for path in self.ref_dir.glob("ref_*"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    async def terminate(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
