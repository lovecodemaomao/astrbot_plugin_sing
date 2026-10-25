import unittest

from sing.args import ArgsError, parse, tokenize


class TokenizeTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(tokenize("/唱歌 夏天 的海"), ["/唱歌", "夏天", "的海"])

    def test_quoted(self):
        self.assertEqual(tokenize('--风格 "轻快 city pop" 夏天'), ["--风格", "轻快 city pop", "夏天"])


class ParseSingTest(unittest.TestCase):
    def test_text_only(self):
        opts = parse("夏天的海", mode="sing")
        self.assertEqual(opts.text, "夏天的海")
        self.assertEqual(opts.style, "")
        self.assertFalse(opts.instrumental)

    def test_value_flags(self):
        opts = parse("夏天的海 --风格 民谣 --音色 少女", mode="sing")
        self.assertEqual(opts.text, "夏天的海")
        self.assertEqual(opts.style, "民谣")
        self.assertEqual(opts.voice, "少女")

    def test_inline_value(self):
        opts = parse('--风格="city pop"', mode="sing")
        self.assertEqual(opts.style, "city pop")

    def test_english_alias(self):
        opts = parse("rain --style lofi --voice 少年", mode="sing")
        self.assertEqual(opts.style, "lofi")
        self.assertEqual(opts.voice, "少年")

    def test_help(self):
        self.assertTrue(parse("--help", mode="sing").want_help)

    def test_unknown_flag(self):
        with self.assertRaises(ArgsError):
            parse("夏天 --乱写 1", mode="sing")

    def test_missing_value(self):
        with self.assertRaises(ArgsError):
            parse("夏天 --风格", mode="sing")

    def test_instrumental_conflicts_with_lyrics(self):
        with self.assertRaises(ArgsError):
            parse("--纯音乐 --歌词 啦啦啦", mode="sing")

    def test_sing_rejects_cover_only_flags(self):
        with self.assertRaises(ArgsError):
            parse("--干声", mode="sing")
        with self.assertRaises(ArgsError):
            parse("--音频 https://example.com/a.mp3", mode="sing")


class ParseCoverTest(unittest.TestCase):
    def test_cover_flags(self):
        opts = parse("--风格 摇滚 --干声 --音频 https://example.com/a.mp3", mode="cover")
        self.assertEqual(opts.style, "摇滚")
        self.assertTrue(opts.dry_vocal)
        self.assertEqual(opts.audio_url, "https://example.com/a.mp3")

    def test_cover_rejects_instrumental(self):
        with self.assertRaises(ArgsError):
            parse("--纯音乐", mode="cover")

    def test_cover_allows_lyrics(self):
        opts = parse('--歌词 "[Verse 1] 你好"', mode="cover")
        self.assertEqual(opts.lyrics, "[Verse 1] 你好")


if __name__ == "__main__":
    unittest.main()
