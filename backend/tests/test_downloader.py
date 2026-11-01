import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yt_dlp

from backend.bot.platforms.media import display_error
from backend.bot.queue.recovery import retryable
from backend.bot.services import downloader
from backend.bot.services.downloader import DownloaderConfig, NO_AUDIO_ERROR, download, format_options

os.environ.setdefault("YT_DOWNLOADER_TESTING", "1")

CONFIG = DownloaderConfig(
    max_bytes=1024, fragment_workers=1, http_chunk_size_mb=1, cookies_file=None, proxy=None,
    js_runtime=None, player_client=None, po_token=None, po_provider_url=None,
)
NO_AUDIO_FAILURE = "ERROR: Postprocessing: WARNING: unable to obtain file audio codec with ffprobe"


def _format(format_id, vcodec, acodec, ext="mp4"):
    return {"format_id": format_id, "vcodec": vcodec, "acodec": acodec, "ext": ext, "url": f"https://example.com/{format_id}"}


class AudioFormatSelectionTests(unittest.TestCase):
    def select(self, formats):
        with tempfile.TemporaryDirectory() as tmpdir, yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            selector = ydl.build_format_selector(format_options(CONFIG, tmpdir, "mp3")["format"])
            context = {"formats": formats, "incomplete_formats": False, "has_merged_format": False}
            return next(iter(selector(context)))["format_id"]

    def test_tiktok_uses_the_videos_soundtrack_instead_of_the_reused_sound(self):
        formats = [
            _format("audio", "none", "mp3", "mp3"),
            _format("h264_540p", "h264", "aac"),
            _format("bytevc1_1080p", "h265", "aac"),
        ]
        self.assertEqual(self.select(formats), "h264_540p")

    def test_tiktok_skips_h265_variants_labelled_as_having_no_audio(self):
        formats = [_format("h264_540p", "h264", "aac"), _format("bytevc1_1080p", "h265", "none")]
        self.assertEqual(self.select(formats), "h264_540p")

    def test_dedicated_audio_streams_are_still_preferred(self):
        formats = [_format("18", "avc1.42001E", "mp4a.40.2"), _format("140", "none", "mp4a.40.2", "m4a")]
        self.assertEqual(self.select(formats), "140")

    def test_formats_without_codec_metadata_remain_usable(self):
        self.assertEqual(self.select([_format("1", None, None)]), "1")

    def test_audio_only_tiktok_posts_fall_back_to_the_sound(self):
        self.assertEqual(self.select([_format("audio", "none", "mp3", "mp3")]), "audio")


class NoAudioDownloadTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmpdir = directory.name
        for target in ("validate_remote_url", "time"):
            patcher = patch.object(downloader, target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_download(self, *outcomes):
        """Each outcome writes the output file, then raises it or returns info."""
        remaining = list(outcomes)
        seen_existing_files = []
        tmpdir = self.tmpdir

        class FakeYoutubeDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, _url, download):
                seen_existing_files.append(sorted(path.name for path in Path(tmpdir).iterdir()))
                Path(tmpdir, "1234.mp3" if remaining[0] is None else "1234.mp4").write_bytes(b"data")
                outcome = remaining.pop(0)
                if outcome is not None:
                    raise outcome
                return {"id": "1234"}

        with patch.object(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            try:
                return download(CONFIG, "https://www.tiktok.com/@u/video/1234", "mp3", self.tmpdir)
            finally:
                self.seen_existing_files = seen_existing_files

    def test_retry_starts_clean_instead_of_reusing_the_silent_file(self):
        _, filename, extension = self.run_download(RuntimeError(NO_AUDIO_FAILURE), None)
        self.assertEqual(self.seen_existing_files, [[], []])
        self.assertEqual((filename.name, extension), ("1234.mp3", "mp3"))

    def test_repeated_silent_files_become_a_permanent_error(self):
        with self.assertLogs("downloader_bot.downloader", "WARNING") as logs:
            with self.assertRaises(ValueError) as caught:
                self.run_download(RuntimeError(NO_AUDIO_FAILURE), RuntimeError(NO_AUDIO_FAILURE))
        self.assertEqual(str(caught.exception), NO_AUDIO_ERROR)
        self.assertFalse(retryable(caught.exception))
        self.assertEqual(list(Path(self.tmpdir).iterdir()), [])
        self.assertTrue(any("event=download_no_audio_stream" in line and "size_bytes=4" in line for line in logs.output))

    def test_no_audio_error_is_translated_for_every_language(self):
        generic = {language: display_error(RuntimeError("boom"), language) for language in ("en", "ru", "az")}
        messages = {language: display_error(ValueError(NO_AUDIO_ERROR), language) for language in generic}
        self.assertEqual(len(set(messages.values())), 3)
        for language, message in messages.items():
            self.assertNotEqual(message, generic[language])

    def test_other_failures_keep_their_original_error(self):
        failure = RuntimeError("ERROR: [TikTok] 1234: Unexpected response from webpage request")
        with self.assertRaises(RuntimeError) as caught:
            self.run_download(failure, failure)
        self.assertIs(caught.exception, failure)
        self.assertTrue(retryable(caught.exception))


if __name__ == "__main__":
    unittest.main()
