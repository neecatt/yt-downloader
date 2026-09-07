import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.bot.persistence import activity_store


class ActivityStoreSafetyTests(unittest.TestCase):
    def test_conversation_query_excludes_hidden_chats(self):
        class Result:
            def fetchall(self):
                return []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.query = query
                self.values = values
                return Result()

        connection = Connection()
        with patch.object(activity_store, "enabled", return_value=True), \
             patch.object(activity_store, "_connect", return_value=connection):
            activity_store.query_conversations()

        self.assertIn("c.admin_hidden_at IS NULL", connection.query)

    def test_hiding_conversation_preserves_rows(self):
        class Cursor:
            rowcount = 1

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.query = query
                self.values = values
                return Cursor()

        connection = Connection()
        with patch.object(activity_store, "enabled", return_value=True), \
             patch.object(activity_store, "_connect", return_value=connection):
            hidden = activity_store.hide_conversation(123)

        self.assertTrue(hidden)
        self.assertTrue(connection.query.startswith("UPDATE bot_contacts"))
        self.assertNotIn("DELETE", connection.query)
        self.assertEqual(connection.values[-1], 123)

    def test_inbound_message_restores_hidden_conversation(self):
        class Cursor:
            rowcount = 1

        class Connection:
            def __init__(self):
                self.queries = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.queries.append((query, values))
                return Cursor()

        connection = Connection()
        with patch.object(activity_store, "enabled", return_value=True), \
             patch.object(activity_store, "_connect", return_value=connection):
            activity_store.record_message(
                chat_id=123, username="user", display_name="User",
                direction="inbound", text="Hello",
            )

        self.assertEqual(len(connection.queries), 2)
        self.assertIn("SET admin_hidden_at = NULL", connection.queries[1][0])

    def test_replacement_status_message_is_attached_only_to_active_job(self):
        class Cursor:
            rowcount = 1

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.query = query
                self.values = values
                return Cursor()

        connection = Connection()
        with patch.object(activity_store, "enabled", return_value=True), \
             patch.object(activity_store, "_connect", return_value=connection):
            updated = activity_store.set_transcription_status_message_id("a" * 32, 456)

        self.assertTrue(updated)
        self.assertIn("status IN ('queued', 'processing')", connection.query)
        self.assertEqual(connection.values[0], 456)
        self.assertEqual(connection.values[-1], "a" * 32)

    def test_test_mode_disables_database_even_when_url_is_present(self):
        with patch.dict(os.environ, {"YT_DOWNLOADER_TESTING": "1", "DATABASE_URL": "postgresql://production"}, clear=True):
            self.assertEqual(activity_store._database_url(), "")
            self.assertFalse(activity_store.enabled())

    def test_anonymous_activity_is_rejected_before_database_access(self):
        with patch.object(activity_store, "enabled", return_value=True), patch.object(activity_store, "_connect") as connect:
            event_id = activity_store.create_event(
                username=None,
                display_name=None,
                chat_type="private",
                chat_id=123,
                source_url="https://youtu.be/example",
                title=None,
                platform="youtube",
                action="download",
            )
        self.assertIsNone(event_id)
        connect.assert_not_called()

    def test_query_events_clamps_page_and_uses_stable_order(self):
        class Result:
            def __init__(self, *, one=None, rows=None):
                self.one = one
                self.rows = rows or []

            def fetchone(self):
                return self.one

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.calls.append((query, values))
                if query.startswith("SELECT COUNT(*) FROM"):
                    return Result(one=(101,))
                if query.startswith("SELECT *"):
                    now = datetime.now(timezone.utc)
                    row = ("a" * 32, "@user", "User", "private", "https://youtu.be/example", "Example", "youtube", "download", None, "started", None, None, None, None, now)
                    return Result(rows=[row])
                return Result(one=(101, 0, 0, 1, 0))

        connection = Connection()
        with patch.object(activity_store, "_connect", return_value=connection):
            result = activity_store.query_events(page=999, page_size=25, action="download", excluded_usernames=["@Alice", "bob_123"])

        event_query, event_values = connection.calls[1]
        self.assertIn("ORDER BY created_at DESC, id DESC", event_query)
        self.assertIn("action = %s", event_query)
        self.assertIn("NOT IN (%s, %s)", event_query)
        self.assertEqual(event_values[:3], ["download", "alice", "bob_123"])
        self.assertEqual(event_values[-2:], [25, 100])
        self.assertEqual(result["page"], 5)
        self.assertEqual(result["total"], 101)

    def test_non_https_activity_source_is_rejected(self):
        with patch.object(activity_store, "enabled", return_value=True), patch.object(activity_store, "_connect") as connect:
            event_id = activity_store.create_event(
                username="@user",
                display_name="User",
                chat_type="private",
                chat_id=123,
                source_url="javascript:alert(1)",
                title=None,
                platform="youtube",
                action="download",
            )
        self.assertIsNone(event_id)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
