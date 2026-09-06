from datetime import datetime, timedelta, timezone
import unittest

from backend.bot.queue.recovery import retry_delay_seconds, retryable
from backend.bot.telegram.status import active_job_status_text


class QueueRecoveryTests(unittest.TestCase):
    def test_unknown_backend_errors_are_retried(self):
        self.assertTrue(retryable(RuntimeError("Modal model loading failed")))
        self.assertTrue(retryable(RuntimeError("Redis connection reset")))
        self.assertTrue(retryable(RuntimeError("transcription service unavailable")))

    def test_clear_input_errors_are_not_retried_forever(self):
        self.assertFalse(retryable(ValueError("Video is private")))
        self.assertFalse(retryable(ValueError("Video not found")))
        self.assertFalse(retryable(ValueError("This video is unavailable")))
        self.assertFalse(retryable(ValueError("unsupported media type")))

    def test_retry_delay_is_bounded_exponential(self):
        self.assertEqual(retry_delay_seconds(0), 10)
        self.assertEqual(retry_delay_seconds(1), 20)
        self.assertEqual(retry_delay_seconds(4), 160)
        self.assertEqual(retry_delay_seconds(99), 300)


class QueueStatusNotificationTests(unittest.TestCase):
    def test_retry_wait_is_shown_instead_of_generic_queue_text(self):
        now = datetime.now(timezone.utc)
        job = {
            "id": "a" * 32,
            "status": "queued",
            "chat_id": 10,
            "status_message_id": 20,
            "language": "en",
            "job_type": "summary",
            "attempts": 2,
            "next_attempt_at": now + timedelta(minutes=10),
        }
        text = active_job_status_text(job, now=now)
        self.assertIn("Attempt 2 paused", text)
        self.assertIn("about 10 min", text)
        self.assertIn("do not send it again", text)

    def test_processing_summary_has_summary_specific_status(self):
        job = {
            "id": "b" * 32,
            "status": "processing",
            "chat_id": 10,
            "status_message_id": 20,
            "language": "en",
            "job_type": "summary",
            "attempts": 1,
            "next_attempt_at": None,
        }
        self.assertIn("Generating the summary", active_job_status_text(job))


if __name__ == "__main__":
    unittest.main()
