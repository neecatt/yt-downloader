import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.bot.persistence import activity_store


class ActivityStoreSafetyTests(unittest.TestCase):
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
