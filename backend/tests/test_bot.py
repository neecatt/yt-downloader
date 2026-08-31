from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import backend.main as bot
    from backend.bot.integrations.r2_cleanup import delete_expired_objects
    from backend.bot.platforms.limits import SlidingWindowLimiter
except ModuleNotFoundError:
    # Also support running discovery from inside the backend service directory.
    import main as bot
    from bot.integrations.r2_cleanup import delete_expired_objects
    from bot.platforms.limits import SlidingWindowLimiter


class FakeMessage:
    def __init__(self, text: str = "", chat_id: int = 10):
        self.text = text
        self.chat_id = chat_id
        self.replies: list[tuple[str, object]] = []
        self.deleted = False
        self.edited: list[str] = []
        self.documents = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs.get("reply_markup")))
        return self

    async def edit_text(self, text: str, **kwargs):
        self.edited.append(text)
        return self

    async def delete(self):
        self.deleted = True

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)


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


class R2CleanupTests(unittest.TestCase):
    def test_expired_cleanup_only_deletes_old_download_objects(self):
        now = datetime.now(timezone.utc)

        class Paginator:
            def paginate(self, **kwargs):
                return [{"Contents": [
                    {"Key": "downloads/old.mp4", "LastModified": now - timedelta(hours=2)},
                    {"Key": "downloads/live.mp4", "LastModified": now - timedelta(minutes=5)},
                    {"Key": "other/old.mp4", "LastModified": now - timedelta(hours=2)},
                ]}]

        class Client:
            def __init__(self):
                self.deleted = []

            def get_paginator(self, name):
                self.paginator_name = name
                return Paginator()

            def delete_objects(self, **kwargs):
                self.deleted.extend(item["Key"] for item in kwargs["Delete"]["Objects"])
                return {"Errors": []}

        client = Client()
        deleted = delete_expired_objects(client, "bucket", prefix="downloads/", retention_seconds=3600)

        self.assertEqual(deleted, 1)
        self.assertEqual(client.deleted, ["downloads/old.mp4"])


class LimiterTests(unittest.TestCase):
    def test_sliding_window_blocks_until_window_expires(self):
        limiter = SlidingWindowLimiter()
        self.assertTrue(limiter.allow("user", limit=2, window_seconds=60, now=100))
        self.assertTrue(limiter.allow("user", limit=2, window_seconds=60, now=110))
        self.assertFalse(limiter.allow("user", limit=2, window_seconds=60, now=120))
        self.assertTrue(limiter.allow("user", limit=2, window_seconds=60, now=161))

    def test_sliding_window_key_storage_is_bounded(self):
        limiter = SlidingWindowLimiter(max_keys=100)
        for index in range(150):
            self.assertTrue(limiter.allow(index, limit=1, window_seconds=3600, now=index))
        self.assertLessEqual(len(limiter._entries), 100)


class PureFunctionTests(unittest.TestCase):
    def setUp(self):
        bot.STATES.clear()
        bot.LANGUAGE_CACHE.clear()
        bot.SUPPORT_PROMPT_LAST_SHOWN.clear()

    def test_extracts_supported_https_links_and_strips_punctuation(self):
        self.assertEqual(bot.extract_url("See https://youtu.be/abc123."), "https://youtu.be/abc123")
        self.assertEqual(bot.extract_url("https://www.tiktok.com/@user/video/1"), "https://www.tiktok.com/@user/video/1")
        self.assertEqual(bot.extract_url("https://www.instagram.com/reel/ABC123/"), "https://www.instagram.com/reel/ABC123/")
        self.assertEqual(bot.extract_url("https://www.facebook.com/reel/ABC123/"), "https://www.facebook.com/reel/ABC123/")
        self.assertEqual(bot.extract_url("https://x.com/example/status/123456789"), "https://x.com/example/status/123456789")
        self.assertEqual(bot.extract_url("https://www.linkedin.com/posts/example_video-123"), "https://www.linkedin.com/posts/example_video-123")
        self.assertIsNone(bot.extract_url("http://youtu.be/abc123"))
        self.assertIsNone(bot.extract_url("https://example.com/video"))

    def test_any_https_mode_rejects_private_hosts(self):
        self.assertEqual(bot.extract_url("https://example.com/video", any_https=True), "https://example.com/video")
        self.assertIsNone(bot.extract_url("https://127.0.0.1/video", any_https=True))
        self.assertIsNone(bot.extract_url("https://localhost/video", any_https=True))

    def test_url_length_is_bounded(self):
        self.assertIsNone(bot.extract_url("https://example.com/" + "a" * 5000, any_https=True))

    def test_activity_platform_classifies_x_and_linkedin(self):
        self.assertEqual(bot._activity_platform("https://x.com/example/status/1"), "x")
        self.assertEqual(bot._activity_platform("https://www.linkedin.com/posts/example_video-1"), "linkedin")

    def test_photo_links_are_detected_as_video_only(self):
        self.assertTrue(bot.is_x_photo_link("https://x.com/example/status/123/photo/1"))
        self.assertFalse(bot.is_x_photo_link("https://x.com/example/status/123"))
        self.assertTrue(bot.should_analyze_media_type("https://www.instagram.com/p/ABC123/"))

    def test_generic_https_is_opt_in(self):
        self.assertIsNone(bot.extract_url("https://example.com/video", any_https=False))
        self.assertEqual(bot.extract_url("https://example.com/video", any_https=True), "https://example.com/video")

    def test_remote_url_rejects_private_and_non_https_targets(self):
        with self.assertRaises(ValueError):
            bot.validate_remote_url("https://127.0.0.1/internal")
        with self.assertRaises(ValueError):
            bot.validate_remote_url("http://example.com/video")

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

    def test_callback_state_count_is_bounded(self):
        update, _ = update_for()
        with patch.object(bot, "MAX_STATE_ENTRIES", 100):
            for index in range(101):
                bot.save_state(update, f"https://youtu.be/{index}")
        self.assertLessEqual(len(bot.STATES), 100)

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
        self.assertEqual(video["max_filesize"], bot.MAX_DOWNLOAD_BYTES)
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
        self.assertIn("publicly available", bot.display_error(Exception("Private Facebook post")))
        self.assertIn("publicly available", bot.display_error(Exception("Facebook: Cannot parse data")))
        self.assertIn("lower quality", bot.display_error(Exception("file too large")))
        self.assertIn("timed out", bot.display_error(Exception("connection timeout")))
        self.assertIn("source rejected", bot.display_error(Exception("HTTP Error 403: Forbidden")))
        self.assertNotIn("secret", bot.display_error(Exception("secret internal stack trace")))

    def test_image_and_carousel_errors_are_video_only(self):
        self.assertIn("only downloads videos and audio", bot.display_error(Exception("image post")))
        self.assertIn("only downloads videos and audio", bot.display_error(Exception("carousel playlist")))

    def test_safe_log_error_redacts_signed_urls(self):
        result = bot.safe_log_error(Exception("failed https://cdn.example/file?token=secret-value"))
        self.assertNotIn("secret-value", result)
        self.assertIn("[url-redacted]", result)

    def test_donation_url_requires_https_without_credentials(self):
        self.assertEqual(bot.validate_donation_url("https://www.buymeacoffee.com/example"), "https://www.buymeacoffee.com/example")
        self.assertIsNone(bot.validate_donation_url("http://www.buymeacoffee.com/example"))
        self.assertIsNone(bot.validate_donation_url("https://user:pass@buymeacoffee.com/example"))

    def test_missing_donation_url_disables_support_and_cooldown_is_enforced(self):
        with patch.object(bot, "DONATION_URL", None), patch.object(bot, "DONATION_PROMPTS_ENABLED", True):
            self.assertIsNone(bot.support_keyboard())
        with patch.object(bot, "DONATION_URL", "https://www.buymeacoffee.com/example"), \
             patch.object(bot, "DONATION_PROMPTS_ENABLED", True), \
             patch.object(bot, "DONATION_PROMPT_COOLDOWN_SECONDS", 100):
            self.assertTrue(bot.support_prompt_allowed(10, 20, now=100))
            bot.mark_support_prompt_shown(10, 20, now=100)
            self.assertFalse(bot.support_prompt_allowed(10, 20, now=150))
            self.assertTrue(bot.support_prompt_allowed(10, 20, now=200))


class AsyncHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.STATES.clear()
        bot.LANGUAGE_CACHE.clear()
        for pending in list(bot.PENDING_DELIVERIES.values()):
            bot.discard_pending_delivery(pending)
        bot.PENDING_DELIVERIES.clear()
        bot.DOWNLOAD_LOCKS.clear()
        bot.SUPPORT_PROMPT_LAST_SHOWN.clear()

    async def test_start_explains_supported_usage(self):
        update, message = update_for()
        await bot.start(update, SimpleNamespace())
        self.assertIn("YouTube", message.replies[0][0])
        self.assertIn("/download", message.replies[0][0])

    async def test_start_shows_support_button_when_configured(self):
        update, message = update_for()
        with patch.object(bot, "DONATION_URL", "https://www.buymeacoffee.com/example"), \
             patch.object(bot, "DONATION_PROMPTS_ENABLED", True):
            await bot.start(update, SimpleNamespace())
        buttons = message.replies[0][1].inline_keyboard
        self.assertTrue(any(button.text == "☕ Support this bot" for row in buttons for button in row))

    async def test_start_shows_language_buttons_and_language_can_be_changed(self):
        update, message = update_for()
        await bot.start(update, SimpleNamespace())
        language_buttons = message.replies[0][1].inline_keyboard[0]
        self.assertEqual([button.callback_data for button in language_buttons], ["lang|en", "lang|ru", "lang|az"])
        query = FakeQuery("lang|ru", message)
        update.callback_query = query
        with patch.object(bot, "activity_store", create=True):
            await bot.language_button_handler(update, SimpleNamespace(), "ru")
        self.assertIn("Добро пожаловать", query.edited[0])

    async def test_settings_command_shows_language_buttons(self):
        update, message = update_for()
        await bot.settings_command(update, SimpleNamespace())
        self.assertEqual(message.replies[0][1].inline_keyboard[0][2].callback_data, "lang|az")

    async def test_help_command_explains_commands_and_supported_platforms(self):
        update, message = update_for()
        await bot.help_command(update, SimpleNamespace())
        self.assertIn("/download", message.replies[0][0])
        self.assertIn("YouTube", message.replies[0][0])
        self.assertIn("/settings", message.replies[0][0])

    async def test_transcribe_command_reports_unconfigured_service(self):
        update, message = update_for()
        with patch.object(bot, "transcription_is_configured", return_value=False):
            await bot.transcribe_command(update, SimpleNamespace(args=["https://youtu.be/abc"]))
        self.assertIn("not available", message.replies[0][0])

    async def test_transcribe_callback_delivers_text_file(self):
        update, message = update_for(chat_id=55, user_id=65)
        key = bot.save_state(update, "https://youtu.be/abc", {"title": "Talk"})
        query = FakeQuery(f"t|{key}", message)
        update.callback_query = query
        try:
            from backend.bot.persistence import activity_store
        except ModuleNotFoundError:
            from bot.persistence import activity_store
        with patch.object(bot, "transcription_is_configured", return_value=True), \
             patch.object(bot, "r2_is_configured", return_value=True), \
             patch.object(bot, "queue_is_configured", return_value=True), \
             patch.object(bot, "enqueue_transcription") as enqueue, \
             patch.object(activity_store, "create_transcription_job", return_value="a" * 32), \
             patch.object(activity_store, "get_transcription_queue_status", return_value={"position": 3, "eta_minutes": 10}):
            await bot.button_handler(update, SimpleNamespace())
        self.assertIn("position 3", query.edited[0].lower())
        self.assertIn("10 min", query.edited[0].lower())
        enqueue.assert_called_once_with("a" * 32)
        self.assertNotIn(key, bot.STATES)

    async def test_transcription_status_edit_failure_does_not_report_queue_failure(self):
        update, message = update_for(chat_id=55, user_id=65)
        key = bot.save_state(update, "https://youtu.be/abc")

        class FailingStatus(FakeQuery):
            async def edit_message_text(self, text: str, **kwargs):
                raise RuntimeError("Telegram edit raced with worker update")

        status = FailingStatus(f"t|{key}", message)
        try:
            from backend.bot.persistence import activity_store
        except ModuleNotFoundError:
            from bot.persistence import activity_store
        with patch.object(bot, "queue_is_configured", return_value=True), \
             patch.object(bot, "enqueue_transcription") as enqueue, \
             patch.object(bot, "_update_activity") as update_activity, \
             patch.object(activity_store, "create_transcription_job", return_value="a" * 32), \
             patch.object(activity_store, "get_transcription_queue_status", return_value={"position": 2, "eta_minutes": 5}):
            await bot._run_transcription(update, status, "https://youtu.be/abc", "en")
        enqueue.assert_called_once_with("a" * 32)
        update_activity.assert_not_called()

    async def test_feedback_command_saves_text_and_confirms(self):
        update, message = update_for()
        context = SimpleNamespace(args=["The", "720p", "option", "works", "well"])
        try:
            from backend.bot.persistence import activity_store
        except ModuleNotFoundError:
            from bot.persistence import activity_store
        with patch.object(activity_store, "create_feedback", return_value="a" * 32) as create_feedback:
            await bot.feedback_command(update, context)
        create_feedback.assert_called_once()
        self.assertEqual(create_feedback.call_args.kwargs["feedback"], "The 720p option works well")
        self.assertIn("saved", message.replies[0][0])

    async def test_feedback_command_requires_text(self):
        update, message = update_for()
        await bot.feedback_command(update, SimpleNamespace(args=[]))
        self.assertIn("/feedback Your message here", message.replies[0][0])

    async def test_support_command_always_works_even_after_prompt_cooldown(self):
        update, message = update_for()
        context = SimpleNamespace(bot=FakeBot())
        with patch.object(bot, "DONATION_URL", "https://www.buymeacoffee.com/example"), \
             patch.object(bot, "DONATION_PROMPTS_ENABLED", True), \
             patch.object(bot, "DONATION_PROMPT_COOLDOWN_SECONDS", 86400):
            bot.mark_support_prompt_shown(10, 20, now=100)
            await bot.support_command(update, context)
        self.assertEqual(len(context.bot.messages), 1)
        self.assertIn("support", context.bot.messages[0]["text"].lower())

    async def test_message_handler_offers_format_buttons(self):
        update, message = update_for("Download https://youtu.be/abc")
        await bot.handle_message(update, SimpleNamespace())
        self.assertEqual(len(message.replies), 1)
        self.assertNotIn("Duration:", message.replies[0][0])
        markup = message.replies[0][1]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("d|720p", " ".join(callbacks))
        self.assertIn("s|", " ".join(callbacks))
        self.assertEqual(len(bot.STATES), 1)

    async def test_message_handler_rejects_unsupported_input(self):
        update, message = update_for("not a video link")
        await bot.handle_message(update, SimpleNamespace())
        self.assertIn("YouTube, TikTok, Instagram, Facebook, X, or LinkedIn", message.replies[0][0])

    async def test_x_photo_link_explains_that_bot_is_video_only(self):
        update, message = update_for("https://x.com/example/status/123/photo/1")
        await bot.handle_message(update, SimpleNamespace())
        self.assertIn("only downloads videos and audio", message.replies[0][0])

    async def test_detected_image_post_is_rejected_without_download_options(self):
        update, message = update_for("https://www.instagram.com/p/ABC123/")
        with patch.object(bot, "analyze_url", side_effect=ValueError("This is an image post")):
            await bot.handle_message(update, SimpleNamespace())
        self.assertIn("only downloads videos and audio", message.edited[0])
        self.assertEqual(len(bot.STATES), 0)

    async def test_download_command_analyzes_link_and_offers_choices(self):
        update, message = update_for()
        context = SimpleNamespace(args=["https://youtu.be/abc"])
        fake_info = {"title": "Example", "duration": 65}
        with patch.object(bot, "analyze_url", return_value=fake_info):
            await bot.download_command(update, context)
        self.assertEqual(len(message.replies), 2)
        self.assertTrue(message.deleted)
        self.assertIn("Example", message.replies[1][0])

    async def test_download_command_reports_analysis_failure(self):
        update, message = update_for()
        context = SimpleNamespace(args=["https://youtu.be/abc"])
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

        with patch.object(bot, "DELIVERY_MODE", "auto"), \
             patch.object(bot, "r2_is_configured", return_value=False), \
             patch.object(bot, "DONATION_URL", "https://www.buymeacoffee.com/example"), \
             patch.object(bot, "DONATION_PROMPTS_ENABLED", True), \
             patch.object(bot, "DONATION_PROMPT_COOLDOWN_SECONDS", 86400), \
             patch.object(bot, "download_sync", side_effect=fake_download):
            await bot.button_handler(update, context)
        self.assertEqual(query.answers, 1)
        self.assertTrue(query.deleted)
        self.assertEqual(len(context.bot.audio), 1)
        self.assertEqual(len(context.bot.messages), 1)
        self.assertTrue(any("Uploading" in text for text in query.edited))
        self.assertNotIn(key, bot.STATES)

    async def test_oversized_media_uses_r2_and_explains_telegram_limit(self):
        update, source_message = update_for(chat_id=31, user_id=41)
        key = bot.save_state(update, "https://www.instagram.com/reel/abc", {"title": "Reel"})
        query = FakeQuery(f"d|720p|{key}", source_message)
        update.callback_query = query
        context = SimpleNamespace(bot=FakeBot())

        def fake_download(url, fmt, tmpdir, progress_callback=None):
            output = Path(tmpdir) / "abc.mp4"
            output.write_bytes(b"large media")
            return {"title": "Reel"}, output, "mp4"

        with patch.object(bot, "DELIVERY_MODE", "auto"), \
             patch.object(bot, "DONATION_URL", "https://www.buymeacoffee.com/example"), \
             patch.object(bot, "DONATION_PROMPTS_ENABLED", True), \
             patch.object(bot, "MAX_UPLOAD_BYTES", 1), \
             patch.object(bot, "r2_is_configured", return_value=True), \
             patch.object(bot, "upload_to_r2", return_value="https://downloads.example/reel") as upload, \
             patch.object(bot, "download_sync", side_effect=fake_download):
            await bot.button_handler(update, context)

        upload.assert_called_once()
        self.assertEqual(len(context.bot.messages), 1)
        self.assertIn("exceeds Telegram's upload limit", context.bot.messages[0]["text"])
        self.assertEqual(context.bot.messages[0]["reply_markup"].inline_keyboard[1][0].text, "☕ Support this bot")

    async def test_auto_mode_asks_for_delivery_when_file_fits_telegram(self):
        update, source_message = update_for(chat_id=32, user_id=42)
        key = bot.save_state(update, "https://youtu.be/abc", {"title": "Song"})
        query = FakeQuery(f"d|mp3|{key}", source_message)
        update.callback_query = query
        context = SimpleNamespace(bot=FakeBot())

        def fake_download(url, fmt, tmpdir, progress_callback=None):
            output = Path(tmpdir) / "abc.mp3"
            output.write_bytes(b"small audio")
            return {"title": "Song"}, output, "mp3"

        with patch.object(bot, "DELIVERY_MODE", "auto"), \
             patch.object(bot, "r2_is_configured", return_value=True), \
             patch.object(bot, "download_sync", side_effect=fake_download):
            await bot.button_handler(update, context)

        self.assertFalse(query.deleted)
        self.assertEqual(len(bot.PENDING_DELIVERIES), 1)
        pending_key = next(iter(bot.PENDING_DELIVERIES))
        self.assertIn("How would you like to receive it?", query.edited[-1])

        delivery_query = FakeQuery(f"p|telegram|{pending_key}", source_message)
        update.callback_query = delivery_query
        await bot.button_handler(update, context)
        self.assertTrue(delivery_query.deleted)
        self.assertEqual(len(context.bot.audio), 1)
        self.assertFalse(bot.PENDING_DELIVERIES)

    async def test_auto_mode_can_upload_under_limit_file_to_r2_on_request(self):
        update, source_message = update_for(chat_id=33, user_id=43)
        key = bot.save_state(update, "https://youtu.be/abc", {"title": "Video"})
        query = FakeQuery(f"d|720p|{key}", source_message)
        update.callback_query = query
        context = SimpleNamespace(bot=FakeBot())

        def fake_download(url, fmt, tmpdir, progress_callback=None):
            output = Path(tmpdir) / "abc.mp4"
            output.write_bytes(b"small video")
            return {"title": "Video"}, output, "mp4"

        with patch.object(bot, "DELIVERY_MODE", "auto"), \
             patch.object(bot, "r2_is_configured", return_value=True), \
             patch.object(bot, "download_sync", side_effect=fake_download), \
             patch.object(bot, "upload_to_r2", return_value="https://downloads.example/video") as upload:
            await bot.button_handler(update, context)
            pending_key = next(iter(bot.PENDING_DELIVERIES))
            delivery_query = FakeQuery(f"p|r2|{pending_key}", source_message)
            update.callback_query = delivery_query
            await bot.button_handler(update, context)

        upload.assert_called_once()
        self.assertTrue(delivery_query.deleted)
        self.assertIn("You chose a temporary download link", context.bot.messages[0]["text"])
        self.assertFalse(bot.PENDING_DELIVERIES)

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
        await bot.send_r2_link(context, 1, "https://downloads.example/file", {"title": "Video"}, "720p", 60 * 1024 * 1024)
        self.assertEqual(len(context.bot.documents), 0)
        self.assertEqual(len(context.bot.messages), 1)
        self.assertIn("Download file", context.bot.messages[0]["reply_markup"].inline_keyboard[0][0].text)
        self.assertIn("exceeds Telegram's upload limit", context.bot.messages[0]["text"])

    async def test_auto_mode_uses_telegram_when_r2_is_not_configured(self):
        with patch.object(bot, "R2_ENDPOINT_URL", "your-endpoint"), patch.object(bot, "R2_ACCESS_KEY_ID", "your-access-key"), patch.object(bot, "R2_SECRET_ACCESS_KEY", "your-secret"), patch.object(bot, "R2_BUCKET_NAME", "your-bucket"):
            self.assertFalse(bot.r2_is_configured())


if __name__ == "__main__":
    unittest.main()
