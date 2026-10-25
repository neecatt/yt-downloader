import importlib.util
import os
import unittest
from unittest.mock import patch

from backend.bot.config.settings import load_settings

CELERY_AVAILABLE = importlib.util.find_spec("celery") is not None


class QueueSettingsTests(unittest.TestCase):
    def test_invalid_numbers_fall_back_to_defaults_instead_of_crashing(self):
        with patch.dict(os.environ, {
            "TRANSCRIPTION_MAX_RETRIES": "two",
            "TRANSCRIPTION_STALE_JOB_SECONDS": "",
            "TRANSCRIPTION_QUEUE_MAX_SIZE": "1e3",
            "ADMIN_REQUESTS_PER_MINUTE": "fast",
        }, clear=True):
            loaded = load_settings()
        self.assertEqual(loaded.queue.max_retries, 2)
        self.assertEqual(loaded.queue.stale_job_seconds, 21600)
        self.assertEqual(loaded.queue.max_size, 100)
        self.assertEqual(loaded.admin.requests_per_minute, 60)

    def test_values_are_clamped_to_safe_bounds(self):
        with patch.dict(os.environ, {
            "TRANSCRIPTION_RECOVERY_INTERVAL_SECONDS": "1",
            "TRANSCRIPTION_STALE_JOB_SECONDS": "5",
            "TRANSCRIPTION_QUEUE_MAX_PER_USER": "0",
            "CELERY_TASK_TIME_LIMIT_SECONDS": "10",
            "ADMIN_REQUESTS_PER_MINUTE": "100000",
        }, clear=True):
            loaded = load_settings()
        self.assertEqual(loaded.queue.recovery_interval_seconds, 30)
        self.assertEqual(loaded.queue.stale_job_seconds, 3600)
        self.assertEqual(loaded.queue.max_per_user, 1)
        self.assertEqual(loaded.queue.task_time_limit_seconds, 3600)
        self.assertEqual(loaded.admin.requests_per_minute, 300)


@unittest.skipUnless(CELERY_AVAILABLE, "celery is required to import the transcription worker")
class WorkerConfigurationTests(unittest.TestCase):
    def setUp(self):
        from backend.bot.workers import transcription as worker
        self.worker = worker
        worker._DOWNLOADER_CONFIG = None
        self.addCleanup(setattr, worker, "_DOWNLOADER_CONFIG", None)

    def test_worker_storage_uses_shared_settings_including_account_endpoint(self):
        with patch.dict(os.environ, {
            "R2_ACCOUNT_ID": "account123",
            "R2_API_TOKEN": "access:secret",
            "R2_BUCKET_NAME": "bucket",
        }, clear=True):
            loaded = load_settings()
        with patch.object(self.worker, "settings", loaded), patch.object(self.worker.storage, "client") as client:
            self.worker._r2_client()
        client.assert_called_once_with("https://account123.r2.cloudflarestorage.com", "access", "secret", "bucket")

    def test_cookie_file_is_prepared_once_per_worker_process(self):
        with patch.object(self.worker, "prepare_cookie_file", return_value="/tmp/cookies.txt") as prepare:
            first = self.worker._worker_downloader_config()
            second = self.worker._worker_downloader_config()
        self.assertIs(first, second)
        prepare.assert_called_once()
        self.assertEqual(first.max_bytes, self.worker.settings.download.max_bytes)

    def test_missing_bot_token_is_reported_without_network_calls(self):
        with patch.dict(os.environ, {}, clear=True):
            loaded = load_settings()
        with patch.object(self.worker, "settings", loaded):
            with self.assertRaisesRegex(RuntimeError, "token is not configured"):
                self.worker._bot_token()


if __name__ == "__main__":
    unittest.main()
