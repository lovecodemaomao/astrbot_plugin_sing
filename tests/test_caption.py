import unittest

from sing.caption import DEFAULT_STYLE, build_caption, describe_voice


class DescribeVoiceTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(describe_voice(""), "")

    def test_preset(self):
        self.assertIn("少女", describe_voice("少女"))

    def test_custom_passthrough(self):
        self.assertEqual(describe_voice("慵懒的爵士嗓"), "慵懒的爵士嗓")


class BuildCaptionTest(unittest.TestCase):
    def test_default_style(self):
        self.assertEqual(build_caption(), DEFAULT_STYLE)

    def test_style_override(self):
        self.assertEqual(build_caption("摇滚"), "摇滚")

    def test_style_and_voice(self):
        caption = build_caption("摇滚", "御姐")
        self.assertTrue(caption.startswith("摇滚"))
        self.assertIn("御姐", caption)

    def test_blank_inputs_fall_back(self):
        self.assertEqual(build_caption("   ", "  ", "默认风格"), "默认风格")


if __name__ == "__main__":
    unittest.main()
