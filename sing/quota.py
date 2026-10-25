"""每日配额：按会话统计，落盘保存，跨重启有效。"""

from __future__ import annotations

import json
import time
from pathlib import Path

__all__ = ["DailyQuota"]


class DailyQuota:
    """简单的「每天每会话 N 次」计数。"""

    def __init__(
        self,
        path: Path | str,
        limit: int,
        *,
        today: str | None = None,
        clock=None,
    ) -> None:
        self.path = Path(path)
        self.limit = max(1, int(limit))
        if clock is not None:
            self._clock = clock
        elif today:
            self._clock = lambda: today
        else:
            self._clock = self._today_str
        self._today = self._clock()
        self._usage: dict[str, int] = {}
        self._load()

    @staticmethod
    def _today_str() -> str:
        return time.strftime("%Y-%m-%d")

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if str(payload.get("date") or "") != self._today:
            return
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self._usage = {
                str(key): int(value)
                for key, value in usage.items()
                if isinstance(value, int) or str(value).isdigit()
            }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": self._today, "usage": self._usage}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _rollover(self) -> None:
        today = self._clock()
        if today != self._today:
            self._today = today
            self._usage.clear()

    def remaining(self, key: str) -> int:
        self._rollover()
        return max(0, self.limit - self._usage.get(str(key), 0))

    def consume(self, key: str) -> bool:
        """扣一次配额；额度用尽返回 False。"""
        self._rollover()
        key = str(key)
        used = self._usage.get(key, 0)
        if used >= self.limit:
            return False
        self._usage[key] = used + 1
        self._save()
        return True
