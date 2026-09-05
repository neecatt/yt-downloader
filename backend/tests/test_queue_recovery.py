import unittest

from backend.bot.queue.recovery import retry_delay_seconds, retryable


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


if __name__ == "__main__":
    unittest.main()
