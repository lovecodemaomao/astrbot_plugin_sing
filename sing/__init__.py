"""sing 包：参数解析、caption 组装、歌词、StepFun 客户端、ASR、参考音频、配额。"""

from . import api, args, asr, audio, caption, lyrics, quota

__all__ = ["api", "args", "asr", "audio", "caption", "lyrics", "quota"]
