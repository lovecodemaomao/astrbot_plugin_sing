import json
import tempfile
import unittest
from pathlib import Path

from sing.lyrics import FALLBACK_LYRICS, clean_lyrics, generate_lyrics
from sing.quota import DailyQuota


class CleanLyricsTest(unittest.TestCase):
    def test_strips_code_fence(self):
        raw = "```\n[Verse 1]\n你好\n```"
        self.assertEqual(clean_lyrics(raw), "[Verse 1]\n你好")

    def test_collapses_blank_lines(self):
        raw = "[Verse 1]\n\n\n你好\n\n[Chorus 1]\n世界"
        self.assertEqual(clean_lyrics(raw), "[Verse 1]\n\n你好\n\n[Chorus 1]\n世界")

    def test_empty(self):
        self.assertEqual(clean_lyrics(""), "")


class FakeProvider:
    def __init__(self, text=None, raises=False):
        self.text = text
        self.raises = raises

    async def text_chat(self, **_):
        if self.raises:
            raise RuntimeError("boom")

        class Response:
            pass

        response = Response()
        response.completion_text = self.text
        return response


class GenerateLyricsTest(unittest.TestCase):
    def test_no_provider_uses_fallback(self):
        result = asyncio_run(generate_lyrics(None, "夏天"))
        self.assertEqual(result, FALLBACK_LYRICS)

    def test_provider_error_uses_fallback(self):
        result = asyncio_run(generate_lyrics(FakeProvider(raises=True), "夏天"))
        self.assertEqual(result, FALLBACK_LYRICS)

    def test_short_output_uses_fallback(self):
        result = asyncio_run(generate_lyrics(FakeProvider("短"), "夏天"))
        self.assertEqual(result, FALLBACK_LYRICS)

    def test_uses_model_output(self):
        text = "[Verse 1]\n夏天的风吹过海面\n浪花把心事推远\n\n[Chorus 1]\n唱吧 唱吧"
        result = asyncio_run(generate_lyrics(FakeProvider(text), "夏天"))
        self.assertEqual(result, text)


class QuotaTest(unittest.TestCase):
    def test_consume_until_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            q = DailyQuota(path, 2, today="2026-01-01")
            self.assertTrue(q.consume("g1"))
            self.assertTrue(q.consume("g1"))
            self.assertFalse(q.consume("g1"))
            self.assertEqual(q.remaining("g1"), 0)
            self.assertTrue(q.consume("g2"))

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            q = DailyQuota(path, 3, today="2026-01-01")
            q.consume("g1")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["date"], "2026-01-01")
            reloaded = DailyQuota(path, 3, today="2026-01-01")
            self.assertEqual(reloaded.remaining("g1"), 2)

    def test_rollover_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            state = {"day": "2026-01-01"}
            q = DailyQuota(path, 1, clock=lambda: state["day"])
            q.consume("g1")
            state["day"] = "2026-01-02"
            self.assertEqual(q.remaining("g1"), 1)


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
