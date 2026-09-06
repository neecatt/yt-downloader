import unittest
from types import SimpleNamespace

from backend.bot.telegram.summary import send_summary, telegram_summary_chunks


class TelegramSummaryTests(unittest.IsolatedAsyncioTestCase):
    def test_summary_is_customer_friendly_bold_and_html_safe(self):
        summary = """**Overview:**
The transcript discusses <new> AI & safety.

**Key Points:**
- **Fast:** Handles work safely.
- Keeps details.
"""
        chunks = telegram_summary_chunks(summary)

        self.assertEqual(len(chunks), 1)
        rendered = chunks[0]
        self.assertIn("<b>🎬 Video overview</b>", rendered)
        self.assertIn("The video discusses &lt;new&gt; AI &amp; safety.", rendered)
        self.assertIn("<b>🔑 Key takeaways</b>", rendered)
        self.assertIn("• <b>Fast:</b> Handles work safely.", rendered)
        self.assertNotIn("**", rendered)
        self.assertNotIn("<new>", rendered)

    def test_long_summary_is_split_under_telegram_limit(self):
        chunks = telegram_summary_chunks("- " + "<&> " * 3000, max_length=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    async def test_delivery_enables_telegram_html(self):
        class Bot:
            def __init__(self):
                self.messages = []

            async def send_message(self, **kwargs):
                self.messages.append(SimpleNamespace(**kwargs))

        bot = Bot()
        await send_summary(bot, 42, "**Video overview**\nUseful summary")

        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(bot.messages[0].chat_id, 42)
        self.assertEqual(bot.messages[0].parse_mode, "HTML")
        self.assertIn("<b>🎬 Video overview</b>", bot.messages[0].text)


if __name__ == "__main__":
    unittest.main()
