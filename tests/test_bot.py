import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

import bot


class FakeTelegramBot:
    def __init__(self):
        self.copies = []
        self.edits = []

    async def copy_message(self, **kwargs):
        self.copies.append(kwargs)
        return SimpleNamespace(message_id=900 + len(self.copies))

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)

    async def edit_message_caption(self, **kwargs):
        self.edits.append(kwargs)


class FakeMessage:
    def __init__(self):
        self.text = ""
        self.reply_markup = None
        self.answers = []

    async def edit_text(self, text, reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, user_id=bot.OWNER_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answer_text = ""

    async def answer(self, text="", **kwargs):
        self.answer_text = text


class BotFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = bot.DB_PATH
        bot.DB_PATH = str(Path(self._tmp.name) / "quantum-test.db")
        bot.init_db()
        with bot.connect_db() as conn:
            for user_id, consent, notifications in ((101, 1, 1), (102, 0, 0), (103, 1, 0)):
                conn.execute("""
                    INSERT INTO users
                    (user_id, status, notifications, created_at, signals_consent, intro_sent)
                    VALUES (?, 'active', ?, ?, ?, 1)
                """, (user_id, notifications, bot.now(), consent))

    async def asyncTearDown(self):
        bot.DB_PATH = self._old_db_path
        self._tmp.cleanup()

    async def test_source_posts_are_opt_in_deduplicated_and_edits_update_copy(self):
        telegram = FakeTelegramBot()
        post = SimpleNamespace(message_id=44, text="EUR/USD BUY M5", caption=None)
        await bot.signals_pro_channel_handler(post, telegram)
        await bot.signals_pro_channel_handler(post, telegram)

        self.assertEqual(len(telegram.copies), 1)
        self.assertEqual(telegram.copies[0]["chat_id"], 101)
        with bot.connect_db() as conn:
            self.assertEqual(
                conn.execute("SELECT user_id, copied_message_id FROM source_deliveries").fetchone(),
                (101, 901),
            )

        edited = SimpleNamespace(
            message_id=44,
            text="EUR/USD BUY M5 ✅",
            caption=None,
            html_text="EUR/USD BUY M5 ✅",
            html_caption=None,
        )
        await bot.signals_pro_edited_handler(edited, telegram)
        self.assertEqual(len(telegram.edits), 1)
        self.assertEqual(telegram.edits[0]["message_id"], 901)
        with bot.connect_db() as conn:
            self.assertTrue(conn.execute(
                "SELECT text FROM source_posts WHERE message_id=44"
            ).fetchone()[0].endswith("✅"))

    async def test_pair_summary_uses_only_recent_source_posts(self):
        with bot.connect_db() as conn:
            conn.execute(
                "INSERT INTO source_posts (message_id, text, created_at) VALUES (?, ?, ?)",
                (55, "EURUSD and BTCUSDT", bot.now()),
            )
            conn.execute(
                "INSERT INTO source_posts (message_id, text, created_at) VALUES (?, ?, ?)",
                (56, "GBP/JPY", "2020-01-01T00:00:00+00:00"),
            )
        self.assertEqual(bot.extract_pairs("EUR/USD + BTCUSDT"), {"EUR/USD", "BTC/USDT"})
        callback = FakeCallback("binary_recent_10")
        await bot.binary_recent_signals(callback)
        self.assertIn("EUR/USD", callback.message.text)
        self.assertIn("BTC/USDT", callback.message.text)
        self.assertNotIn("GBP/JPY", callback.message.text)

    async def test_additive_migration_preserves_legacy_user(self):
        legacy_db = Path(self._tmp.name) / "legacy.db"
        conn = sqlite3.connect(legacy_db)
        try:
            conn.execute("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
                    full_name TEXT DEFAULT '', status TEXT DEFAULT 'active',
                    notifications INTEGER DEFAULT 1, language TEXT DEFAULT 'ru',
                    created_at TEXT
                )
            """)
            conn.execute(
                "INSERT INTO users (user_id, full_name, created_at) VALUES (7, 'Legacy', '2024-01-01')"
            )
            conn.commit()
        finally:
            conn.close()
        bot.DB_PATH = str(legacy_db)
        bot.init_db()
        with bot.connect_db() as conn:
            self.assertEqual(conn.execute("SELECT full_name FROM users WHERE user_id=7").fetchone()[0], "Legacy")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            self.assertTrue({"signals_consent", "intro_sent"}.issubset(columns))

    async def test_investing_rss_parser_stores_images_and_deduplicates(self):
        rss = b'''<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Test feed</title><item><guid>story-1</guid><title>Market story</title><description><![CDATA[<p>Sample description</p>]]></description><link>https://example.com/story</link><pubDate>Sat, 14 Nov 2026 10:00:00 GMT</pubDate><media:content url="https://example.com/photo.jpg" medium="image"/></item></channel></rss>'''

        async def feed(_request):
            return web.Response(body=rss, content_type="application/rss+xml")

        app = web.Application()
        app.router.add_get("/feed", feed)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        old_url, old_allowed = bot.NEWS_RSS_URL, bot.NEWS_REPUBLISH_ALLOWED
        try:
            port = site._server.sockets[0].getsockname()[1]
            bot.NEWS_RSS_URL = f"http://127.0.0.1:{port}/feed"
            bot.NEWS_REPUBLISH_ALLOWED = True
            await bot.fetch_and_store_news()
            await bot.fetch_and_store_news()
            with bot.connect_db() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM news").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT image_url FROM news").fetchone()[0], "https://example.com/photo.jpg")
                self.assertEqual(conn.execute("SELECT description FROM news").fetchone()[0], "Sample description")
        finally:
            bot.NEWS_RSS_URL, bot.NEWS_REPUBLISH_ALLOWED = old_url, old_allowed
            await runner.cleanup()

    async def test_admin_statistics_panel_edits_existing_message(self):
        callback = FakeCallback("admin_stats")
        await bot.admin_buttons(callback)
        self.assertIn("СТАТИСТИКА", callback.message.text)
        self.assertIsNotNone(callback.message.reply_markup)
        self.assertEqual(callback.answer_text, "")

    async def test_autotrade_copy_and_support_button_are_truthful_and_valid(self):
        user_message = FakeMessage()
        user_message.from_user = SimpleNamespace(id=777, username="test", full_name="Test User")
        await bot.autotrade_handler(user_message)
        text, markup = user_message.answers[0]
        self.assertIn("просто выберите действие", text.lower())
        self.assertNotIn("зарегистрируйтесь у брокера", text.lower())
        self.assertNotIn("14659", text)
        self.assertNotIn("Статус подключения", text)
        registration, support = markup.inline_keyboard[0][0], markup.inline_keyboard[1][0]
        self.assertEqual(registration.style, "primary")
        self.assertEqual(support.style, "success")
        self.assertIsNone(support.callback_data)
        self.assertEqual(registration.text, "➡️ Регистрация у брокера")
        self.assertEqual(support.text, "➡️ Подключить автоторговлю")
        self.assertEqual(support.url, bot.SUPPORT_URL)
        self.assertIn("https://t.me/copy_broker_BO_bot?text=", support.url)
        self.assertNotIn("готовое сообщение", text.lower())
        self.assertNotIn("Здравствуйте! 🤝 Хочу подключить автоторговлю!", text)
        self.assertNotIn("отправьте администратору сообщение", text.lower())

    async def test_binary_menu_hides_crypto_list_and_exposes_binary_signals(self):
        labels = [row[0].text for row in bot.binary_menu_keyboard().inline_keyboard]
        self.assertNotIn("₿ СПИСОК КРИПТОПАР", labels)
        self.assertIn("📈 СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ", labels)

    async def test_user_crypto_pair_list_matches_requested_twenty_pairs(self):
        callback = FakeCallback("crypto_pairs")
        await bot.crypto_pairs_handler(callback)
        self.assertEqual(len(bot.CRYPTO_PAIRS), 20)
        self.assertIn("1. <code>BTC/USDT</code>", callback.message.text)
        self.assertIn("20. <code>FIL/USDT</code>", callback.message.text)
        self.assertEqual(callback.message.reply_markup.inline_keyboard[0][0].callback_data, "binary_menu")

    async def test_signal_history_normalizes_status_and_hides_source_checkmark_noise(self):
        self.assertEqual(bot.signal_result_marker("GBPJPY m5 вверх ⌛\n✅"), "⏳")
        self.assertEqual(bot.signal_result_marker("GBPCHF m5 вверх ⭕"), "⭕")
        self.assertEqual(bot.signal_result_marker("AUDJPY m5 вверх ✔"), "✅")
        self.assertEqual(
            bot.compact_signal_text("GBPJPY m5 вверх ⌛\n✅"),
            "GBP/JPY · m5 · вверх",
        )

    async def test_forwarded_signal_collapses_mixed_result_emojis(self):
        telegram = FakeTelegramBot()
        post = SimpleNamespace(text="GBPJPY m5 вверх ☑️\n✅ ✔", caption=None)
        await bot.decorate_signal_copy(telegram, 101, 901, post)
        self.assertEqual(len(telegram.edits), 1)
        self.assertEqual(telegram.edits[0]["text"], "GBPJPY m5 вверх ✅")

    async def test_animated_emoji_require_an_exact_pack_match(self):
        old_pack = bot._CUSTOM_EMOJI_PACK
        old_ids = bot._CUSTOM_EMOJI_FALLBACK_IDS
        try:
            bot._CUSTOM_EMOJI_PACK = {
                "🤖": ["robot-id"], "✨": ["sparkle-id"], "🗓": ["calendar-id"],
                "✅": ["check-id"],
            }
            bot._CUSTOM_EMOJI_FALLBACK_IDS = ["animated-id"]
            markup = bot.ReplyKeyboardMarkup(
                keyboard=[[bot.KeyboardButton(text="🗓 Экономический календарь")]],
                resize_keyboard=True,
            )
            bot.apply_custom_button_icons(markup)
            button = markup.keyboard[0][0]
            self.assertEqual(button.icon_custom_emoji_id, "calendar-id")
            self.assertEqual(button.text, "Экономический календарь")
            rendered = bot.render_custom_emojis("🤖 ✅ 🗓")
            self.assertIn('emoji-id="robot-id"', rendered)
            self.assertIn('emoji-id="check-id"', rendered)
            self.assertIn("🗓", rendered)
        finally:
            bot._CUSTOM_EMOJI_PACK = old_pack
            bot._CUSTOM_EMOJI_FALLBACK_IDS = old_ids

    async def test_main_keyboard_has_single_signal_history_entry(self):
        labels = [button.text for row in bot.main_keyboard.keyboard for button in row]
        self.assertIn("🕘 ИСТОРИЯ СИГНАЛОВ", labels)
        self.assertFalse(any("МОИ СИГНАЛЫ" in label for label in labels))
        self.assertFalse(hasattr(bot, "my_signals_handler"))


if __name__ == "__main__":
    unittest.main()
