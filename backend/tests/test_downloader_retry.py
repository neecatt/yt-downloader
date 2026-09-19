"""Regression tests for transient yt-dlp download failures."""

import tempfile
import unittest
from unittest.mock import patch

from backend.bot.services.downloader import DownloaderConfig, download


class DownloaderRetryTests(unittest.TestCase):
    def setUp(self):
        self.config = DownloaderConfig(
            max_bytes=100_000_000,
            fragment_workers=1,
            http_chunk_size_mb=10,
            cookies_file=None,
            proxy=None,
            js_runtime="node",
            player_client=None,
            po_token=None,
            po_provider_url=None,
        )

    def test_youtube_bot_check_is_not_repeated_immediately(self):
        challenge = Exception("ERROR: [youtube] 7r4ikZHm9AI: Sign in to confirm you’re not a bot")
        with tempfile.TemporaryDirectory() as directory, \
             patch("backend.bot.services.downloader.validate_remote_url"), \
             patch("backend.bot.services.downloader.yt_dlp.YoutubeDL") as ydl, \
             patch("backend.bot.services.downloader.time.sleep") as sleep:
            ydl.return_value.__enter__.return_value.extract_info.side_effect = challenge
            with self.assertRaisesRegex(Exception, "Sign in to confirm"):
                download(self.config, "https://youtu.be/7r4ikZHm9AI", "mp3", directory)
            self.assertEqual(ydl.call_count, 1)
            sleep.assert_not_called()

    def test_other_transient_error_retains_local_retry(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("backend.bot.services.downloader.validate_remote_url"), \
             patch("backend.bot.services.downloader.yt_dlp.YoutubeDL") as ydl, \
             patch("backend.bot.services.downloader.time.sleep") as sleep:
            ydl.return_value.__enter__.return_value.extract_info.side_effect = OSError("network timeout")
            with self.assertRaisesRegex(OSError, "network timeout"):
                download(self.config, "https://youtu.be/7r4ikZHm9AI", "mp3", directory)
            self.assertEqual(ydl.call_count, 2)
            sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
