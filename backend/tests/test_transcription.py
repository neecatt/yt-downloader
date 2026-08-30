import os
import unittest
from unittest.mock import patch

try:
    from backend.bot.integrations.transcription import (
        format_transcript,
        transcript_filename,
        transcription_is_configured,
        validate_transcription_url,
    )
except ModuleNotFoundError:
    from bot.integrations.transcription import (
        format_transcript,
        transcript_filename,
        transcription_is_configured,
        validate_transcription_url,
    )


class TranscriptionTests(unittest.TestCase):
    def test_queue_requires_private_redis_url(self):
        try:
            from backend.bot.queue import queue_is_configured
        except ModuleNotFoundError:
            from bot.queue import queue_is_configured
        with patch.dict(os.environ, {"TRANSCRIPTION_QUEUE_ENABLED": "true"}, clear=True):
            self.assertFalse(queue_is_configured())

    def test_only_supported_https_hosts_are_accepted(self):
        self.assertEqual(validate_transcription_url("https://youtu.be/example"), "https://youtu.be/example")
        with self.assertRaises(ValueError):
            validate_transcription_url("http://youtu.be/example")
        with self.assertRaises(ValueError):
            validate_transcription_url("https://example.com/audio")
        with self.assertRaises(ValueError):
            validate_transcription_url("https://user:pass@youtu.be/example")

    def test_modal_configuration_requires_both_token_values(self):
        with patch.dict(os.environ, {
            "TRANSCRIPTION_ENABLED": "true",
            "MODAL_TOKEN_ID": "id",
            "MODAL_TOKEN_SECRET": "secret",
        }, clear=True):
            self.assertTrue(transcription_is_configured())
        with patch.dict(os.environ, {"TRANSCRIPTION_ENABLED": "true", "MODAL_TOKEN_ID": "id"}, clear=True):
            self.assertFalse(transcription_is_configured())
        with patch.dict(os.environ, {"TRANSCRIPTION_ENABLED": "false", "MODAL_TOKEN_ID": "id", "MODAL_TOKEN_SECRET": "secret"}, clear=True):
            self.assertFalse(transcription_is_configured())

    def test_format_transcript_includes_timestamps_and_fallback_text(self):
        output = format_transcript({
            "title": "A / Talk",
            "language": "en",
            "segments": [{"start": 65, "text": " Hello   world "}],
            "text": "Hello world",
        })
        self.assertIn("A / Talk", output)
        self.assertIn("[01:05] Hello world", output)

        fallback = format_transcript({"title": "Talk", "language": "en", "segments": [], "text": "Only text"})
        self.assertIn("Only text", fallback)

    def test_filename_is_safe_and_bounded(self):
        filename = transcript_filename("bad/:title?" + "x" * 200)
        self.assertTrue(filename.endswith(".txt"))
        self.assertNotIn("/", filename)
        self.assertLessEqual(len(filename), 125)


if __name__ == "__main__":
    unittest.main()
