from __future__ import annotations

"""Check Telegram error routing and safe diagnostics without network access."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from telegram.error import BadRequest, NetworkError

os.environ["YT_DOWNLOADER_TESTING"] = "1"

from backend.bot.telegram.errors import handle_error


class TelegramErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_bad_gateway_is_reported_as_a_network_warning(self):
        error = NetworkError("Bad Gateway https://api.telegram.org/botSECRET/getUpdates")
        with self.assertLogs("downloader_bot.telegram", "WARNING") as logs:
            await handle_error(None, SimpleNamespace(error=error))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("event=telegram_network_error scope=polling", logs.output[0])
        self.assertNotIn("SECRET", logs.output[0])
        self.assertNotIn("https://", logs.output[0])

    async def test_rejected_request_is_not_misclassified_as_a_network_outage(self):
        with self.assertLogs("downloader_bot.telegram", "ERROR") as logs:
            await handle_error(object(), SimpleNamespace(error=BadRequest("Message to edit not found")))
        self.assertIn("event=telegram_handler_error scope=update error_type=BadRequest", logs.output[0])

    async def test_unexpected_error_does_not_log_the_update_contents(self):
        update = SimpleNamespace(text="private-video-link", caption="private-caption")
        with self.assertLogs("downloader_bot.telegram", "ERROR") as logs:
            await handle_error(update, SimpleNamespace(error=RuntimeError("handler failed")))
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("private-", logs.output[0])

    async def test_missing_error_is_ignored(self):
        with self.assertNoLogs("downloader_bot.telegram"):
            await handle_error(None, SimpleNamespace(error=None))


class TelegramErrorRegistrationTests(unittest.TestCase):
    def test_application_registers_the_error_handler(self):
        from backend import main as application

        with patch.object(application, "BOT_TOKEN", "test-token"), \
             patch.object(application.activity_store, "initialize"), \
             patch.object(application.monetization_store, "initialize"), \
             patch.object(application, "start_admin_api"), \
             patch.object(application, "ApplicationBuilder") as builder_type:
            builder = builder_type.return_value
            for method in ("token", "post_init", "post_shutdown", "base_url", "base_file_url"):
                getattr(builder, method).return_value = builder
            application.main()

        builder.build.return_value.add_error_handler.assert_called_once_with(handle_error)


if __name__ == "__main__":
    unittest.main()
