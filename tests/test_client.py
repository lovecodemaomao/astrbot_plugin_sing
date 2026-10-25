import asyncio
import base64
import json
import unittest

from sing.api import MusicApiError, StepFunMusicClient


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def text(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        status, body = self.responses.pop(0)
        return FakeResponse(status, body)


def make_client(responses, **kwargs):
    session = FakeSession(responses)
    client = StepFunMusicClient(
        "test-key",
        session_factory=lambda: session,
        sleep=_noop_sleep,
        **kwargs,
    )
    return client, session


async def _noop_sleep(_):
    return None


def run(coro):
    return asyncio.run(coro)


class SubmitTest(unittest.TestCase):
    def test_submit_sends_expected_payload(self):
        client, session = make_client([(200, json.dumps({"task_id": "abc-123"}))])
        task_id = run(client.submit(caption="city pop", lyrics="[Verse 1]\n你好", instrumental=False))
        self.assertEqual(task_id, "abc-123")
        payload = session.calls[0]["json"]
        self.assertEqual(payload["task"], "text_to_music")
        self.assertEqual(payload["caption"], "city pop")
        self.assertEqual(payload["lyrics"], "[Verse 1]\n你好")
        self.assertNotIn("instrumental", payload)
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer test-key")

    def test_instrumental_omits_lyrics(self):
        client, session = make_client([(200, json.dumps({"task_id": "t1"}))])
        run(client.submit(caption="纯音乐", instrumental=True))
        payload = session.calls[0]["json"]
        self.assertTrue(payload["instrumental"])
        self.assertNotIn("lyrics", payload)

    def test_cover_payload_has_song_audio(self):
        client, session = make_client([(200, json.dumps({"task_id": "t2"}))])
        run(client.submit(caption="rock", lyrics="la", task="music_cover", song_audio=b"abc"))
        payload = session.calls[0]["json"]
        self.assertEqual(payload["task"], "music_cover")
        self.assertEqual(base64.b64decode(payload["song_audio"]), b"abc")
        self.assertNotIn("vocal_audio", payload)

    def test_missing_task_id_raises(self):
        client, _ = make_client([(200, json.dumps({}))])
        with self.assertRaises(MusicApiError):
            run(client.submit(caption="x"))

    def test_401_maps_to_hint(self):
        body = json.dumps({"error": {"type": "not_allowed", "message": "invalid token"}})
        client, _ = make_client([(401, body)])
        with self.assertRaises(MusicApiError) as ctx:
            run(client.submit(caption="x"))
        self.assertIn("API Key", str(ctx.exception))


class WaitTest(unittest.TestCase):
    def test_success_returns_audio(self):
        audio = b"mp3-bytes"
        body = json.dumps({"status": "SUCCESS", "audio": base64.b64encode(audio).decode()})
        client, session = make_client(
            [
                (200, json.dumps({"status": "PENDING"})),
                (200, json.dumps({"status": "RUNNING"})),
                (200, body),
            ],
            poll_interval=1,
            max_wait=30,
        )
        result = run(client.wait("task-1"))
        self.assertEqual(result, audio)
        self.assertEqual(len(session.calls), 3)

    def test_failed_raises_with_stage_hint(self):
        body = json.dumps(
            {
                "status": "FAILED",
                "error": {"stage": "no_speech_detected", "message": "no voice"},
            }
        )
        client, _ = make_client([(200, body)], poll_interval=1, max_wait=30)
        with self.assertRaises(MusicApiError) as ctx:
            run(client.wait("task-2"))
        self.assertIn("人声", str(ctx.exception))

    def test_timeout_raises(self):
        client, _ = make_client(
            [(200, json.dumps({"status": "RUNNING"}))] * 100,
            poll_interval=1,
            max_wait=2,
        )
        with self.assertRaises(MusicApiError) as ctx:
            run(client.wait("task-3"))
        self.assertIn("超时", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
