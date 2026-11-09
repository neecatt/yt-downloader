import os
import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yt_dlp

from backend.bot.platforms.media import display_error
from backend.bot.platforms.security import safe_log_url
from backend.bot.integrations.ytdlp_logging import YtdlpLogger
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


class YouTubeAccessTests(unittest.TestCase):
    def test_comma_separated_clients_are_passed_as_individual_clients(self):
        for provider in (None, "http://provider:4416"):
            with self.subTest(provider=bool(provider)):
                config = replace(CONFIG, player_client=" mweb, tv, web_safari, ", po_provider_url=provider)
                options = downloader.base_options(config, "/tmp/download")
                self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["mweb", "tv", "web_safari"])

    def test_empty_client_list_keeps_the_automatic_policy(self):
        config = replace(CONFIG, player_client=" , ")
        self.assertNotIn("extractor_args", downloader.base_options(config, "/tmp/download"))
        config = replace(config, po_provider_url="http://provider:4416")
        options = downloader.base_options(config, "/tmp/download")
        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["default", "mweb"])

    def test_provider_keeps_cookies_and_tries_alternative_clients(self):
        config = replace(CONFIG, cookies_file="/tmp/cookies.txt", po_provider_url="http://provider:4416")
        options = downloader.base_options(config, "/tmp/download")
        self.assertEqual(options["cookiefile"], config.cookies_file)
        self.assertEqual(options["extractor_args"], {
            "youtube": {"player_client": ["default", "mweb"], "fetch_pot": ["always"]},
            "youtubepot-bgutilhttp": {"base_url": [config.po_provider_url]},
        })

    def test_explicit_clients_and_tokens_are_preserved(self):
        config = replace(CONFIG, player_client="web", po_token="web.gvs:test", po_provider_url="http://provider:4416")
        options = downloader.base_options(config, "/tmp/download")
        self.assertEqual(options["extractor_args"]["youtube"], {
            "player_client": ["web"], "po_token": ["web.gvs:test"], "fetch_pot": ["always"],
        })

    def test_without_provider_yt_dlp_keeps_its_own_defaults(self):
        self.assertNotIn("extractor_args", downloader.base_options(CONFIG, "/tmp/download"))

    def test_automatic_mode_includes_the_real_yt_dlp_defaults_without_account_cookies(self):
        config = replace(CONFIG, po_provider_url="http://provider:4416")
        with tempfile.TemporaryDirectory() as tmpdir:
            options = downloader.base_options(config, tmpdir)
            self.assertNotIn("cookiefile", options)
            with yt_dlp.YoutubeDL(options) as ydl:
                extractor = ydl.get_info_extractor("Youtube")
                with patch.object(extractor, "_jsc_director", create=True) as js:
                    js.providers.values.return_value = [SimpleNamespace(is_available=lambda: True)]
                    clients = extractor._get_requested_clients("https://youtu.be/test", {}, False)
        self.assertTrue(set(extractor._DEFAULT_CLIENTS).issubset(clients))
        self.assertIn("mweb", clients)

    def test_legacy_embedded_setting_uses_the_maintained_automatic_policy(self):
        config = replace(CONFIG, player_client=" tv_embedded ", po_provider_url="http://provider:4416")
        options = downloader.base_options(config, "/tmp/download")
        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["default", "mweb"])

    def test_real_yt_dlp_receives_three_clients_instead_of_one_unsupported_name(self):
        config = replace(CONFIG, player_client="mweb,tv,web_safari", po_provider_url="http://provider:4416")
        with tempfile.TemporaryDirectory() as tmpdir, yt_dlp.YoutubeDL(downloader.base_options(config, tmpdir)) as ydl:
            extractor = ydl.get_info_extractor("Youtube")
            self.assertEqual(extractor._configuration_arg("player_client"), ["mweb", "tv", "web_safari"])

    def test_real_yt_dlp_auto_policy_skips_optional_player_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir, yt_dlp.YoutubeDL(downloader.base_options(CONFIG, tmpdir)) as ydl:
            extractor = ydl.get_info_extractor("Youtube")
            with patch.object(extractor, "_pot_director") as director:
                result = extractor._fetch_po_token("mweb", context="player", required=False, video_id="test")
        self.assertIsNone(result)
        director.get_po_token.assert_not_called()

    def test_real_yt_dlp_requests_optional_tokens_from_the_configured_provider(self):
        config = replace(CONFIG, po_provider_url="http://provider:4416")
        for context in ("player", "gvs"):
            with self.subTest(context=context):
                with tempfile.TemporaryDirectory() as tmpdir, yt_dlp.YoutubeDL(downloader.base_options(config, tmpdir)) as ydl:
                    extractor = ydl.get_info_extractor("Youtube")
                    with patch.object(extractor, "_pot_director") as director:
                        director.get_po_token.return_value = "test-token"
                        result = extractor._fetch_po_token("mweb", context=context, required=False, video_id="test")
                self.assertEqual(result, "test-token")
                director.get_po_token.assert_called_once()
                request = director.get_po_token.call_args.args[0]
                self.assertEqual(request.context.value, context)
                self.assertEqual(request.internal_client_name, "mweb")
                self.assertFalse(request.bypass_cache)

    def test_provider_failure_does_not_fabricate_a_token(self):
        config = replace(CONFIG, po_provider_url="http://provider:4416")
        with tempfile.TemporaryDirectory() as tmpdir, yt_dlp.YoutubeDL(downloader.base_options(config, tmpdir)) as ydl:
            extractor = ydl.get_info_extractor("Youtube")
            with patch.object(extractor, "_pot_director") as director:
                director.get_po_token.return_value = None
                result = extractor._fetch_po_token("mweb", context="player", required=False, video_id="test")
        self.assertIsNone(result)
        director.get_po_token.assert_called_once()

    def test_analysis_keeps_provider_warnings_enabled(self):
        with patch.object(downloader, "validate_remote_url"), patch.object(downloader.yt_dlp, "YoutubeDL") as ydl:
            ydl.return_value.__enter__.return_value.extract_info.return_value = {"id": "test"}
            downloader.analyze(CONFIG, "https://youtu.be/test", "/tmp/download")
        options = ydl.call_args.args[0]
        self.assertFalse(options["no_warnings"])
        self.assertIsInstance(options["logger"], YtdlpLogger)

    def test_real_yt_dlp_surfaces_provider_warnings_without_raw_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir, contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertLogs("downloader_bot.ytdlp", "WARNING") as logs:
                with yt_dlp.YoutubeDL(downloader.base_options(CONFIG, tmpdir)) as ydl:
                    ydl.report_warning("Plugin and HTTP server major versions are mismatched. https://provider/ping?secret=hidden")
                    with self.assertRaises(yt_dlp.utils.DownloadError):
                        ydl.report_error("Sign in to confirm you're not a bot https://youtu.be/test?token=hidden")
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(any("major versions are mismatched" in line for line in logs.output))
        self.assertTrue(any("event=ytdlp_error" in line for line in logs.output))
        self.assertNotIn("hidden", " ".join(logs.output))
        self.assertNotIn("https://", " ".join(logs.output))

    def test_debug_secrets_are_not_logged_and_provider_requests_are_visible(self):
        logger = YtdlpLogger()
        with self.assertLogs("downloader_bot.ytdlp", "INFO") as logs:
            logger.debug("[debug] Generated POT: secret-token")
            logger.debug("[debug] cookies: secret-cookie")
            logger.info("media title https://youtu.be/private-video")
            logger.debug("[youtube] [pot:bgutil:http] Generating a gvs PO Token for mweb client via bgutil HTTP server")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("event=ytdlp_po_token_requested", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    def test_logged_source_has_no_credentials_video_id_or_query(self):
        for url in (
            "https://youtu.be/private-video?token=hidden#fragment",
            "https://user:password@youtu.be/private-video",
        ):
            self.assertEqual(safe_log_url(url), "https://youtu.be")

    def test_download_reports_access_configuration_without_credential_values(self):
        config = replace(
            CONFIG, cookies_file="/secret-cookie-path", proxy="https://user:secret-proxy@proxy.example",
            po_provider_url="http://provider.example/secret-provider-path", js_runtime="node",
        )
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(downloader, "validate_remote_url"), \
             patch.object(downloader.time, "sleep"), \
             patch.object(downloader.yt_dlp, "YoutubeDL") as ydl, \
             self.assertLogs("downloader_bot.downloader", "INFO") as logs:
            ydl.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError("network timeout")
            with self.assertRaisesRegex(RuntimeError, "network timeout"):
                download(config, "https://youtu.be/test", "mp3", tmpdir)
        events = [line for line in logs.output if "event=download_access_config" in line]
        self.assertEqual(len(events), 1)
        self.assertIn("provider_configured=True cookies_configured=True proxy_configured=True js_runtime_configured=True", events[0])
        self.assertNotIn("secret", " ".join(logs.output))


class YouTubeAutomaticRetryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmpdir = directory.name
        self.config = replace(CONFIG, po_provider_url="http://provider:4416")
        self.seen_clients = []
        self.seen_token_policies = []
        self.seen_options = []
        for target in ("validate_remote_url", "time.sleep"):
            patcher = patch(f"backend.bot.services.downloader.{target}")
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target == "time.sleep":
                self.sleep = mock

    def run_download(self, *outcomes, config=None, progress_callback=None):
        remaining = list(outcomes)
        seen_clients = self.seen_clients
        seen_token_policies = self.seen_token_policies
        seen_options = self.seen_options
        tmpdir = self.tmpdir

        class FakeYoutubeDL:
            def __init__(self, options):
                seen_options.append(dict(options))
                args = options.get("extractor_args", {}).get("youtube", {})
                seen_clients.append(list(args.get("player_client", [])))
                seen_token_policies.append(list(args.get("fetch_pot", [])))

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, _url, download):
                outcome = remaining.pop(0)
                if outcome is not None:
                    raise outcome
                Path(tmpdir, "clip.mp3").write_bytes(b"audio")
                return {"id": "test", "title": "Clip"}

        with patch.object(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            return download(config or self.config, "https://youtu.be/test", "mp3", self.tmpdir, progress_callback)

    def test_bot_check_uses_the_existing_second_attempt_for_a_different_client(self):
        error = yt_dlp.utils.DownloadError("ERROR: [youtube] test: Sign in to confirm you’re not a bot")
        with self.assertLogs("downloader_bot.downloader", "INFO") as logs:
            _, filename, extension = self.run_download(error, None)
        self.assertEqual(self.seen_clients, [["default", "mweb"], ["web_safari"]])
        self.assertEqual(self.seen_token_policies, [["always"], ["always"]])
        self.assertEqual((filename.read_bytes(), extension), (b"audio", "mp3"))
        self.sleep.assert_called_once_with(2)
        self.assertTrue(any("event=youtube_client_fallback" in line for line in logs.output))

    def test_rejected_fallback_still_raises_after_two_attempts(self):
        error = yt_dlp.utils.DownloadError("ERROR: [youtube] test: Sign in to confirm you're not a bot")
        with self.assertRaises(yt_dlp.utils.DownloadError) as caught:
            self.run_download(error, error)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(self.seen_clients), 2)
        self.assertEqual(list(Path(self.tmpdir).iterdir()), [])

    def test_successful_first_attempt_does_not_add_requests_or_delays(self):
        self.run_download(None)
        self.assertEqual(self.seen_clients, [["default", "mweb"]])
        self.sleep.assert_not_called()

    def test_explicit_client_selection_is_preserved_on_retry(self):
        error = yt_dlp.utils.DownloadError("ERROR: [youtube] test: Sign in to confirm you're not a bot")
        self.run_download(error, None, config=replace(self.config, player_client="mweb"))
        self.assertEqual(self.seen_clients, [["mweb"], ["mweb"]])

    def test_ordinary_network_and_private_video_errors_do_not_change_clients(self):
        for text in ("network timeout", "ERROR: [youtube] test: Private video. Please sign in", "HTTP Error 403: Forbidden"):
            with self.subTest(error=text):
                self.seen_clients.clear()
                self.run_download(RuntimeError(text), None)
                self.assertEqual(self.seen_clients, [["default", "mweb"], ["default", "mweb"]])

    def test_other_platforms_do_not_trigger_the_youtube_fallback(self):
        error = RuntimeError("ERROR: [other] Sign in to confirm you're not a bot")
        self.run_download(error, None)
        self.assertEqual(self.seen_clients, [["default", "mweb"], ["default", "mweb"]])

    def test_without_a_provider_the_existing_yt_dlp_policy_is_preserved(self):
        error = yt_dlp.utils.DownloadError("ERROR: [youtube] test: Sign in to confirm you're not a bot")
        self.run_download(error, None, config=CONFIG)
        self.assertEqual(self.seen_clients, [[], []])

    def test_fallback_preserves_resource_limits_provider_proxy_and_progress_hooks(self):
        config = replace(self.config, proxy="http://proxy.example:8080", max_bytes=20)
        error = yt_dlp.utils.DownloadError("ERROR: [youtube] test: Sign in to confirm you're not a bot")

        def progress(_data):
            pass

        self.run_download(error, None, config=config, progress_callback=progress)
        for options in self.seen_options:
            self.assertEqual(options["max_filesize"], config.max_bytes)
            self.assertEqual(options["proxy"], config.proxy)
            self.assertEqual(options["socket_timeout"], 30)
            self.assertEqual(options["progress_hooks"], [progress])
            self.assertEqual(options["postprocessor_hooks"], [progress])
            self.assertEqual(options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"], [config.po_provider_url])
            self.assertNotIn("cookiefile", options)


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
