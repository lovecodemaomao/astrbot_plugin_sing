"""阶跃星辰 StepAudio 3 Music 客户端：提交任务、轮询、取回音频。

只依赖 aiohttp；会话构造与 sleep 都可注入，便于单元测试。
"""

from __future__ import annotations

import asyncio
import base64
import json

import aiohttp

__all__ = ["MusicApiError", "StepFunMusicClient"]

DEFAULT_BASE_URL = "https://api.stepfun.com/v1/audio/music"
DEFAULT_MODEL = "stepaudio-3-music-preview"

_STATUS_HINTS = {
    400: "请求参数不合法",
    401: "API Key 无效或已失效",
    402: "账户额度不足",
    404: "模型不存在或该账号没有权限",
    429: "请求太频繁，稍后再试",
    451: "内容未通过审核",
    500: "服务端内部错误",
    503: "服务繁忙，请稍后再试",
}


class MusicApiError(RuntimeError):
    """音乐接口调用失败。"""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        error_type: str = "",
        stage: str = "",
        task_id: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.stage = stage
        self.task_id = task_id
        self.retryable = retryable


class StepFunMusicClient:
    """极简的 StepFun Music 异步客户端。"""

    def __init__(
        self,
        api_key: str,
        *,
        model_id: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval: float = 8.0,
        max_wait: float = 480.0,
        timeout: float = 60.0,
        session_factory=None,
        sleep=asyncio.sleep,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model_id = model_id or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.poll_interval = max(1.0, float(poll_interval))
        self.max_wait = max(30.0, float(max_wait))
        self.timeout = max(5.0, float(timeout))
        self._session_factory = session_factory
        self._sleep = sleep

    # -- 基础设施 ---------------------------------------------------------
    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _raise_for_status(self, status: int, body: str) -> None:
        hint = _STATUS_HINTS.get(status, f"HTTP {status}")
        error_type = ""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                error_type = str(error.get("type") or "")
                detail = str(error.get("message") or "")
                if detail:
                    hint = f"{hint}（{detail}）"
        raise MusicApiError(
            hint,
            status=status,
            error_type=error_type,
            retryable=status in {429, 500, 503},
        )

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with (
            self._session() as session,
            session.post(url, json=payload, headers=self._headers()) as response,
        ):
            status = response.status
            body = await response.text()
        if status >= 400:
            self._raise_for_status(status, body)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MusicApiError("接口返回了无法解析的内容") from exc
        if not isinstance(data, dict):
            raise MusicApiError("接口返回格式异常")
        return data

    # -- 业务 -------------------------------------------------------------
    async def submit(
        self,
        *,
        caption: str,
        lyrics: str | None = None,
        instrumental: bool = False,
        task: str = "text_to_music",
        song_audio: bytes | None = None,
        vocal_audio: bytes | None = None,
        response_format: str = "mp3",
    ) -> str:
        """提交生成任务，返回 task_id。入参按 StepFun 文档语义组装。"""
        payload: dict = {
            "task": task,
            "model_id": self.model_id,
            "caption": (caption or "").strip(),
            "response_format": response_format,
        }
        if lyrics:
            payload["lyrics"] = lyrics
        if instrumental:
            payload["instrumental"] = True
        if song_audio is not None:
            payload["song_audio"] = base64.b64encode(song_audio).decode("ascii")
        if vocal_audio is not None:
            payload["vocal_audio"] = base64.b64encode(vocal_audio).decode("ascii")

        data = await self._post("submit", payload)
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            raise MusicApiError("提交成功但没有返回 task_id")
        return task_id

    async def query(self, task_id: str) -> dict:
        return await self._post("query", {"task_id": task_id})

    async def wait(self, task_id: str) -> bytes:
        """轮询直到任务结束；成功返回音频字节。"""
        waited = 0.0
        last_status = ""
        while waited < self.max_wait:
            await self._sleep(self.poll_interval)
            waited += self.poll_interval
            data = await self.query(task_id)
            status = str(data.get("status") or "")
            last_status = status

            if status == "SUCCESS":
                audio = data.get("audio") or ""
                try:
                    raw = base64.b64decode(audio)
                except (ValueError, TypeError) as exc:
                    raise MusicApiError("任务成功但音频数据损坏", task_id=task_id) from exc
                if not raw:
                    raise MusicApiError("任务成功但没有音频数据", task_id=task_id)
                return raw

            if status == "FAILED":
                error = data.get("error") or {}
                stage = str(error.get("stage") or "")
                message = str(error.get("message") or "未知原因")
                raise MusicApiError(
                    f"生成失败：{_STAGE_HINTS.get(stage, message)}",
                    stage=stage,
                    task_id=task_id,
                )

        raise MusicApiError(
            f"等待生成超时（{int(self.max_wait)} 秒，最后状态 {last_status or '未知'}）",
            task_id=task_id,
        )

    async def generate(self, **kwargs) -> tuple[str, bytes]:
        """提交并等待完成，返回 (task_id, 音频字节)。"""
        task_id = await self.submit(**kwargs)
        return task_id, await self.wait(task_id)


_STAGE_HINTS = {
    "audio_transcode": "参考音频无法解码或格式不支持",
    "no_speech_detected": "参考音频里没有检测到有效人声",
    "censor": "内容被安全审核拦截",
    "internal": "服务端内部错误，请稍后重试",
}
