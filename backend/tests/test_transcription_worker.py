import asyncio
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from backend.bot.config.settings import load_settings

os.environ.setdefault("YT_DOWNLOADER_TESTING", "1")

CELERY_AVAILABLE = importlib.util.find_spec("celery") is not None
JOB_ID = "a" * 32
SOURCE_REFUSED = RuntimeError("ERROR: [TikTok] 1: Unexpected response from webpage request")
LOGGER = "downloader_bot.transcription_worker"


class Retried(Exception):
    pass


class DownloadAttemptSettingsTests(unittest.TestCase):
    def test_attempts_default_and_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_settings().queue.max_download_attempts, 9)
        for value, expected in (("0", 1), ("500", 50)):
            with patch.dict(os.environ, {"TRANSCRIPTION_MAX_DOWNLOAD_ATTEMPTS": value}, clear=True):
                self.assertEqual(load_settings().queue.max_download_attempts, expected)


@unittest.skipUnless(CELERY_AVAILABLE, "celery is required to import the transcription worker")
class StatusUpdateTests(unittest.TestCase):
    def setUp(self):
        from backend.bot.workers import transcription as worker
        self.worker = worker
        self.job = {"id": JOB_ID, "chat_id": 10, "status_message_id": 20}

    def edit_failing_with(self, error):
        client = MagicMock()
        client.__aenter__.return_value.edit_message_text = AsyncMock(side_effect=error)
        with patch.object(self.worker, "Bot", return_value=client), patch.object(self.worker, "_bot_token", return_value="token"):
            asyncio.run(self.worker._edit_status(self.job, "text"))

    def test_unchanged_text_is_not_reported_as_a_failure(self):
        with self.assertNoLogs(LOGGER, "WARNING"):
            self.edit_failing_with(BadRequest("Message is not modified: specified new message content"))

    def test_other_rejected_edits_are_still_logged(self):
        with self.assertLogs(LOGGER, "WARNING"):
            self.edit_failing_with(BadRequest("Message to edit not found"))


@unittest.skipUnless(CELERY_AVAILABLE, "celery is required to import the transcription worker")
class DownloadAttemptLimitTests(unittest.TestCase):
    def setUp(self):
        from backend.bot.workers import transcription as worker
        self.worker = worker
        self.task = worker.process_transcription
        self.store = self.start(patch.object(worker, "activity_store"))
        self.monetization = self.start(patch.object(worker, "monetization_store"))
        self.edit_status = self.start(patch.object(worker, "_edit_status", new=AsyncMock()))
        self.retry = self.start(patch.object(self.task, "retry", side_effect=Retried()))
        self.start(patch.object(worker, "initialize_worker_state"))
        self.start(patch.object(worker, "_refresh_queue_statuses", new=AsyncMock()))
        self.start(patch.object(worker, "_delete_r2_object"))
        self.start(patch.object(worker, "MAX_DOWNLOAD_ATTEMPTS", 9))
        self.store.claim_transcription_job.return_value = True

    def start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def run_job(self, attempts):
        self.store.get_transcription_job.return_value = {
            "id": JOB_ID, "status": "queued", "chat_id": 10, "status_message_id": 20, "language": "en",
            "job_type": "transcription", "attempts": attempts, "activity_id": None,
            "entitlement_operation_id": "operation", "source_url": "https://www.tiktok.com/@u/video/1",
        }
        return self.task.run(JOB_ID)

    def final_status(self):
        return self.store.update_transcription_job.call_args.kwargs["status"]

    def test_source_failure_is_retried_below_the_limit(self):
        with patch.object(self.worker, "_download_sync", side_effect=SOURCE_REFUSED):
            with self.assertRaises(Retried):
                self.run_job(attempts=8)
        self.assertEqual(self.final_status(), "queued")
        self.monetization.release.assert_not_called()

    def test_source_failure_at_the_limit_fails_and_releases_credits(self):
        with patch.object(self.worker, "_download_sync", side_effect=SOURCE_REFUSED):
            with self.assertRaises(RuntimeError):
                self.run_job(attempts=9)
        self.retry.assert_not_called()
        self.assertEqual(self.final_status(), "failed")
        self.monetization.release.assert_called_once_with("operation", "transcription_permanent_failure")
        self.assertIn("couldn't download", self.edit_status.await_args.args[1])

    def test_exhausted_cycle_below_the_limit_waits_for_the_reconciler(self):
        with patch.object(self.worker, "_download_sync", side_effect=SOURCE_REFUSED):
            with patch.object(type(self.task.request), "retries", self.worker.MAX_RETRIES, create=True):
                result = self.run_job(attempts=3)
        self.assertEqual(result, {"status": "retry_wait", "job_id": JOB_ID})
        self.assertEqual(self.final_status(), "queued")

    def test_outage_after_download_stays_durable_past_the_limit(self):
        downloaded = ({"title": "Clip", "duration": 5}, Path("clip.mp3"), "mp3")
        with patch.object(self.worker, "_download_sync", return_value=downloaded), \
                patch.object(self.worker, "_upload_to_r2", return_value=("https://r2.example/clip", "key")), \
                patch.object(self.worker, "transcribe_audio_url_sync", side_effect=RuntimeError("Modal model loading failed")):
            with self.assertRaises(Retried):
                self.run_job(attempts=40)
        self.assertEqual(self.final_status(), "queued")
        self.monetization.release.assert_not_called()

    def test_silent_media_fails_on_the_first_attempt_with_a_clear_message(self):
        with patch.object(self.worker, "_download_sync", side_effect=ValueError("This media has no audio track")):
            with self.assertRaises(ValueError):
                self.run_job(attempts=1)
        self.retry.assert_not_called()
        self.assertEqual(self.final_status(), "failed")
        self.monetization.release.assert_called_once()
        self.assertIn("no sound", self.edit_status.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
