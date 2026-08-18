from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yt_downloader_bot as bot


class FakeMessage:
    def __init__(self, text: str = "", chat_id: int = 10):
        self.text = text
        self.chat_id = chat_id
        self.replies: list[tuple[str, object]] = []
        self.deleted = False
        self.edited: list[str] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs.get("reply_markup")))
        return self

    async def edit_text(self, text: str, **kwargs):
        self.edited.append(text)
        return self

    async def delete(self):
        self.deleted = True


class FakeBot:
    def __init__(self):
        self.audio = []
        self.videos = []
        self.documents = []
        self.actions = []
        self.messages = []

    async def send_chat_action(self, **kwargs):
        self.actions.append(kwargs)

    async def send_audio(self, **kwargs):
        self.audio.append(kwargs)

    async def send_video(self, **kwargs):
        self.videos.append(kwargs)

    async def send_document(self, **kwargs):
        self.documents.append(kwargs)

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class FakeQuery:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answers = 0
        self.edited: list[str] = []
        self.deleted = False

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text: str, **kwargs):
        self.edited.append(text)

    async def delete_message(self):
        self.deleted = True


def update_for(text: str = "", *, chat_id: int = 10, user_id: int = 20):
    message = FakeMessage(text, chat_id)
    return (
        SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=chat_id),
            effective_user=SimpleNamespace(id=user_id),
        ),
        message,
    )


class PureFunctionTests(unittest.TestCase):
    def setUp(self):
        bot.STATES.clear()

    def test_extracts_supported_https_links_and_strips_punctuation(self):
        self.assertEqual(bot.extract_url("See https://youtu.be/abc123."), "https://youtu.be/abc123")
        self.assertEqual(bot.extract_url("https://www.tiktok.com/@user/video/1"), "https://www.tiktok.com/@user/video/1")
        self.assertIsNone(bot.extract_url("http://youtu.be/abc123"))
        self.assertIsNone(bot.extract_url("https://example.com/video"))

    def test_any_https_mode_rejects_private_hosts(self):
        self.assertEqual(bot.extract_url("https://example.com/video", any_https=True), "https://example.com/video")
        self.assertIsNone(bot.extract_url("https://127.0.0.1/video", any_https=True))
        self.assertIsNone(bot.extract_url("https://localhost/video", any_https=True))

    def test_callback_state_is_bound_to_chat_and_user(self):
        update, _ = update_for(chat_id=10, user_id=20)
        key = bot.save_state(update, "https://youtu.be/abc", {"title": "Test"})
        self.assertIsNotNone(bot.get_state(key, update))
        other_chat, _ = update_for(chat_id=11, user_id=20)
        other_user, _ = update_for(chat_id=10, user_id=21)
        self.assertIsNone(bot.get_state(key, other_chat))
        self.assertIsNone(bot.get_state(key, other_user))

    def test_expired_state_is_removed(self):
        update, _ = update_for()
        key = bot.save_state(update, "https://youtu.be/abc")
        bot.STATES[key].created_at = 0
        self.assertIsNone(bot.get_state(key, update))
        self.assertNotIn(key, bot.STATES)

    def test_format_and_filename_helpers(self):
        self.assertEqual(bot.format_duration(125), "2:05")
        self.assertEqual(bot.format_duration(None), "unknown")
        self.assertEqual(bot.safe_filename("unsafe/title:*?", "mp4"), "unsafetitle.mp4")
        self.assertEqual(bot.safe_filename("", "mp3"), "download.mp3")

    def test_ydl_options_cover_audio_video_and_invalid_formats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio = bot.ydl_options(tmpdir, "mp3")
            video = bot.ydl_options(tmpdir, "720p")
            best = bot.ydl_options(tmpdir, "best")
        self.assertEqual(audio["postprocessors"][0]["preferredcodec"], "mp3")
        self.assertIn("b[height<=720][ext=mp4]", video["format"])
        self.assertEqual(best["format"], "bv*+ba/b")
        with self.assertRaises(ValueError):
            bot.ydl_options("/tmp", "4k")

    def test_pot_provider_configures_mweb_and_private_provider(self):
        with patch.object(bot, "YTDLP_POT_PROVIDER_URL", "http://bgutil-provider.railway.internal:4416"), \
             patch.object(bot, "YTDLP_PLAYER_CLIENT", None):
            options = bot.ydl_base_options("/tmp/download")
        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["mweb"])
        self.assertEqual(
            options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"],
            ["http://bgutil-provider.railway.internal:4416"],
        )

    def test_legacy_tv_embedded_client_is_replaced_when_provider_is_enabled(self):
        with patch.object(bot, "YTDLP_POT_PROVIDER_URL", "http://provider:4416"), \
             patch.object(bot, "YTDLP_PLAYER_CLIENT", "tv_embedded"):
            options = bot.ydl_base_options("/tmp/download")
        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["mweb"])

    def test_cookie_file_from_base64_requires_netscape_format(self):
        original_b64 = bot.YTDLP_COOKIES_B64
        original_file = bot.YTDLP_EFFECTIVE_COOKIES_FILE
        try:
            bot.YTDLP_COOKIES_B64 = "bm90IGNvb2tpZXM="
            with self.assertRaises(RuntimeError):
                bot.prepare_cookie_file()
            cookie_header = "# Netscape HTTP Cookie File\n"
            encoded = base64.b64encode(cookie_header.encode()).decode()
            bot.YTDLP_COOKIES_B64 = f" {encoded[:8]}\n{encoded[8:]} "
            cookie_path = bot.prepare_cookie_file()
            self.assertTrue(Path(cookie_path).read_bytes().startswith(b"# Netscape HTTP Cookie File"))
        finally:
            bot.YTDLP_COOKIES_B64 = original_b64
            bot.YTDLP_EFFECTIVE_COOKIES_FILE = original_file

    def test_progress_text_renders_percentage_speed_and_eta(self):
        text = bot.progress_text(
            {
                "status": "downloading",
                "downloaded_bytes": 50 * 1024 * 1024,
                "total_bytes": 100 * 1024 * 1024,
                "speed": 2 * 1024 * 1024,
                "eta": 125,
            },
            "720p",
        )
        self.assertIn("50.0%", text)
        self.assertIn("2.0 MB/s", text)
        self.assertIn("ETA 2:05", text)
        self.assertIn("█", text)

    def test_progress_text_handles_unknown_total(self):
        text = bot.progress_text({"status": "downloading", "downloaded_bytes": 2 * 1024 * 1024}, "mp3")
        self.assertIn("2.0 MB", text)

    def test_progress_text_handles_processing_steps(self):
        self.assertIn("Merging", bot.progress_text({"status": "finished"}, "720p"))
        self.assertIn("Preparing", bot.progress_text({"status": "started"}, "720p"))

    def test_error_messages_do_not_leak_internal_details(self):
        self.assertIn("private", bot.display_error(Exception("Private video")))
        self.assertIn("lower quality", bot.display_error(Exception("file too large")))
        self.assertIn("timed out", bot.display_error(Exception("connection timeout")))
        self.assertIn("source rejected", bot.display_error(Exception("HTTP Error 403: Forbidden")))
        self.assertNotIn("secret", bot.display_error(Exception("secret internal stack trace")))


class AsyncHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.STATES.clear()
        bot.DOWNLOAD_LOCKS.clear()

    async def test_start_explains_supported_usage(self):
        update, message = update_for()
        await bot.start(update, SimpleNamespace())
        self.assertIn("YouTube", message.replies[0][0])
        self.assertIn("/download", message.replies[0][0])

    async def test_message_handler_offers_format_buttons(self):
        update, message = update_for("Download https://youtu.be/abc")
        await bot.handle_message(update, SimpleNamespace())
        self.assertEqual(len(message.replies), 1)
        markup = message.replies[0][1]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("d|720p", " ".join(callbacks))
        self.assertEqual(len(bot.STATES), 1)

    async def test_message_handler_rejects_unsupported_input(self):
        update, message = update_for("not a video link")
        await bot.handle_message(update, SimpleNamespace())
        self.assertIn("YouTube or TikTok", message.replies[0][0])

    async def test_download_command_analyzes_link_and_offers_choices(self):
        update, message = update_for()
        context = SimpleNamespace(args=["https://example.com/video"])
        fake_info = {"title": "Example", "duration": 65}
        with patch.object(bot, "analyze_url", return_value=fake_info):
            await bot.download_command(update, context)
        self.assertEqual(len(message.replies), 2)
        self.assertTrue(message.deleted)
        self.assertIn("Example", message.replies[1][0])

    async def test_download_command_reports_analysis_failure(self):
        update, message = update_for()
        context = SimpleNamespace(args=["https://example.com/video"])
        with patch.object(bot, "analyze_url", side_effect=Exception("private video")):
            await bot.download_command(update, context)
        self.assertTrue(any("private" in text.lower() for text in message.edited))

    async def test_button_handler_downloads_and_sends_mp3(self):
        update, source_message = update_for(chat_id=30, user_id=40)
        key = bot.save_state(update, "https://youtu.be/abc", {"title": "Song"})
        query = FakeQuery(f"d|mp3|{key}", source_message)
        update.callback_query = query
        context = SimpleNamespace(bot=FakeBot())

        def fake_download(url, fmt, tmpdir, progress_callback=None):
            if progress_callback:
                progress_callback({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
                progress_callback({"status": "finished"})
            output = Path(tmpdir) / "abc.mp3"
            output.write_bytes(b"fake audio")
            return {"title": "Song"}, output, "mp3"

        with patch.object(bot, "DELIVERY_MODE", "telegram"), patch.object(bot, "download_sync", side_effect=fake_download):
            await bot.button_handler(update, context)
        self.assertEqual(query.answers, 1)
        self.assertTrue(query.deleted)
        self.assertEqual(len(context.bot.audio), 1)
        self.assertTrue(any("Uploading" in text for text in query.edited))
        self.assertNotIn(key, bot.STATES)

    async def test_button_handler_rejects_expired_or_unknown_callback(self):
        update, message = update_for()
        query = FakeQuery("d|720p|missing", message)
        update.callback_query = query
        context = SimpleNamespace(bot=FakeBot())
        await bot.button_handler(update, context)
        self.assertIn("expired", query.edited[0])

    async def test_send_file_uses_document_for_non_mp4(self):
        context = SimpleNamespace(bot=FakeBot())
        with tempfile.TemporaryDirectory() as tmpdir:
            filename = Path(tmpdir) / "clip.webm"
            filename.write_bytes(b"data")
            await bot.send_file(context, 1, filename, {"title": "Clip"}, "webm", "best")
        self.assertEqual(len(context.bot.documents), 1)

    async def test_send_file_enforces_upload_limit(self):
        context = SimpleNamespace(bot=FakeBot())
        with tempfile.TemporaryDirectory() as tmpdir:
            filename = Path(tmpdir) / "large.mp4"
            filename.write_bytes(b"data")
            with patch.object(bot, "MAX_UPLOAD_BYTES", 1):
                with self.assertRaises(ValueError):
                    await bot.send_file(context, 1, filename, {"title": "Large"}, "mp4", "720p")

    async def test_r2_link_message_contains_browser_download_button(self):
        context = SimpleNamespace(bot=FakeBot())
        await bot.send_r2_link(context, 1, "https://downloads.example/file", {"title": "Video"}, "720p")
        self.assertEqual(len(context.bot.documents), 0)
        self.assertEqual(len(context.bot.messages), 1)
        self.assertIn("Download file", context.bot.messages[0]["reply_markup"].inline_keyboard[0][0].text)

    async def test_auto_mode_uses_telegram_when_r2_is_not_configured(self):
        with patch.object(bot, "R2_ENDPOINT_URL", "your-endpoint"), patch.object(bot, "R2_ACCESS_KEY_ID", "your-access-key"), patch.object(bot, "R2_SECRET_ACCESS_KEY", "your-secret"), patch.object(bot, "R2_BUCKET_NAME", "your-bucket"):
            self.assertFalse(bot.r2_is_configured())


if __name__ == "__main__":
    unittest.main()
