import unittest

from sing.audio import _video_site


class VideoSourceTest(unittest.TestCase):
    def test_supported_public_sites(self):
        self.assertTrue(_video_site("https://www.bilibili.com/video/BV123"))
        self.assertTrue(_video_site("https://b23.tv/abc"))

    def test_rejects_impostor_and_local_urls(self):
        self.assertFalse(_video_site("https://bilibili.com.evil.example/video/BV123"))
        self.assertFalse(_video_site("http://127.0.0.1/video/BV123"))
        self.assertFalse(_video_site("https://bilibili.com:8080/video/BV123"))


if __name__ == "__main__":
    unittest.main()
