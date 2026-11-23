import sqlite3
import tempfile
import unittest
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from aiohttp import web

import bot
import mini_app_server


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

    async def edit_reply_markup(self, reply_markup=None):
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
        self.assertEqual(telegram.edits[0]["text"], "EUR/USD BUY M5 ✅")
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

    async def test_statistics_counts_final_results_and_ignores_pending_posts(self):
        with bot.connect_db() as conn:
            for message_id, text in (
                (61, "EUR/USD BUY M5 ✅"),
                (62, "GBP/JPY m5 вниз ❌"),
                (63, "USD/CHF m5 вверх ⌛"),
                (64, "Новости без валютной пары"),
            ):
                conn.execute(
                    "INSERT INTO source_posts (message_id, text, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (message_id, text, bot.now(), bot.now()),
                )
        message = FakeMessage()
        message.from_user = SimpleNamespace(id=101, username="tester", full_name="Tester")
        await bot.statistics_handler(message)
        text = message.answers[0][0]
        self.assertIn("Сигналов за сутки: 3", text)
        self.assertIn("WIN: 1", text)
        self.assertIn("LOSS: 1", text)
        self.assertEqual(bot.signal_result_marker("USDCHF m5 вверх ⌛"), "")

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
        self.assertIn("выберите действие:", text.lower())
        self.assertNotIn("зарегистрируйтесь у брокера", text.lower())
        self.assertNotIn("14659", text)
        self.assertNotIn("Статус подключения", text)
        registration, support = markup.inline_keyboard[0][0], markup.inline_keyboard[1][0]
        self.assertEqual(registration.style, "success")
        self.assertEqual(support.style, "success")
        self.assertEqual(registration.callback_data, "choose_broker")
        self.assertIsNone(support.callback_data)
        self.assertEqual(registration.text, "➡️ Регистрация у брокера")
        self.assertEqual(support.text, "➡️ Подключить автоторговлю")
        self.assertEqual(support.url, bot.SUPPORT_URL)
        self.assertIn("https://t.me/copy_broker_BO_bot?text=", support.url)
        self.assertNotIn("готовое сообщение", text.lower())
        self.assertNotIn("Здравствуйте! 🤝 Хочу подключить автоторговлю!", text)
        self.assertNotIn("отправьте администратору сообщение", text.lower())

    async def test_registration_button_opens_two_green_broker_links(self):
        callback = FakeCallback("choose_broker", user_id=101)
        await bot.broker_choice_handler(callback)
        choices = callback.message.reply_markup.inline_keyboard
        self.assertEqual(len(choices), 3)
        intrade, binodex, back = (row[0] for row in choices)
        self.assertEqual((intrade.text, intrade.url, intrade.style),
                         ("INTRADE BAR", "https://go.intrade.bar/n4FmpAFBYfvE", "success"))
        self.assertEqual((binodex.text, binodex.url, binodex.style),
                         ("BinoDex", "https://bdclick.app/smart/DLreJY", "success"))
        self.assertEqual((back.text, back.callback_data, back.style),
                         ("⬅️ Назад", "broker_back_autotrade", "primary"))

    async def test_broker_picker_back_restores_autotrade_actions(self):
        callback = FakeCallback("broker_back_autotrade", user_id=101)
        await bot.broker_back_autotrade_handler(callback)
        actions = callback.message.reply_markup.inline_keyboard
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0][0].callback_data, "choose_broker")
        self.assertEqual(actions[1][0].url, bot.SUPPORT_URL)

    async def test_broker_picker_from_signal_returns_to_signal_actions(self):
        callback = FakeCallback("choose_broker_signal", user_id=101)
        await bot.broker_choice_from_signal_handler(callback)
        back = callback.message.reply_markup.inline_keyboard[2][0]
        self.assertEqual(back.callback_data, "broker_back_signal")

        callback = FakeCallback("broker_back_signal", user_id=101)
        await bot.broker_back_signal_handler(callback)
        self.assertEqual(
            callback.message.reply_markup.inline_keyboard[0][0].callback_data,
            "choose_broker_signal",
        )

    async def test_binary_menu_hides_crypto_list_and_exposes_binary_signals(self):
        labels = [row[0].text for row in bot.binary_menu_keyboard().inline_keyboard]
        self.assertNotIn("₿ СПИСОК КРИПТОПАР", labels)
        self.assertEqual(labels, ["💱 Все валютные пары", "🕘 За последние 10 минут"])

    async def test_mini_app_init_data_requires_valid_telegram_signature(self):
        token = "123456:unit-test-token"
        fields = {
            "auth_date": str(int(time.time())),
            "user": json.dumps({"id": 991, "first_name": "Test"}, separators=(",", ":")),
        }
        check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        signed = urlencode(fields)
        self.assertEqual(mini_app_server.validate_telegram_init_data(signed, token)["id"], 991)
        with self.assertRaises(mini_app_server.MiniAppAuthError):
            mini_app_server.validate_telegram_init_data(signed.replace("991", "992"), token)

    async def test_mini_app_daily_stats_use_tashkent_calendar_day(self):
        now = datetime.now(bot.LOCAL_TZ)
        self.assertTrue(mini_app_server._is_tashkent_today(now.isoformat()))
        self.assertFalse(mini_app_server._is_tashkent_today((now - timedelta(days=1)).isoformat()))
        self.assertFalse(mini_app_server._is_tashkent_today("not-a-timestamp"))

    async def test_user_crypto_pair_list_matches_requested_twenty_pairs(self):
        callback = FakeCallback("crypto_pairs")
        await bot.crypto_pairs_handler(callback)
        self.assertEqual(len(bot.CRYPTO_PAIRS), 20)
        self.assertIn("1. <code>BTC/USDT</code>", callback.message.text)
        self.assertIn("20. <code>FIL/USDT</code>", callback.message.text)
        self.assertEqual(callback.message.reply_markup.inline_keyboard[0][0].callback_data, "binary_menu")

    async def test_signal_history_normalizes_status_and_hides_source_checkmark_noise(self):
        self.assertEqual(bot.signal_result_marker("GBPJPY m5 вверх ⌛\n✅"), "✅")
        self.assertEqual(bot.signal_result_kind("GBPJPY m5 вверх ⌛\n✅"), "win")
        self.assertEqual(bot.signal_result_marker("GBPCHF m5 вверх ⭕"), "❌")
        self.assertEqual(bot.signal_result_kind("GBPCHF m5 вверх ⭕"), "loss")
        self.assertEqual(bot.signal_result_marker("AUDJPY m5 вверх ✔"), "✅")
        self.assertEqual(
            bot.compact_signal_text("GBPJPY m5 вверх ⌛\n✅"),
            "GBP/JPY · m5 · вверх",
        )

    async def test_forwarded_signal_edit_preserves_source_emoji_and_entities(self):
        telegram = FakeTelegramBot()
        source_entities = [SimpleNamespace(type="custom_emoji", custom_emoji_id="source-check")]
        post = SimpleNamespace(
            text="GBPJPY m5 вверх ⌛ ⌛ ✅",
            caption=None,
            entities=source_entities,
        )
        await bot.decorate_signal_copy(telegram, 101, 901, post)
        self.assertEqual(len(telegram.edits), 1)
        self.assertEqual(telegram.edits[0]["text"], "GBPJPY m5 вверх ⌛ ⌛ ✅")
        self.assertEqual(telegram.edits[0]["entities"], source_entities)

    async def test_animated_emoji_require_an_exact_pack_match(self):
        old_pack = bot._CUSTOM_EMOJI_PACK
        try:
            bot._CUSTOM_EMOJI_PACK = {
                "🤖": ["robot-id"], "✨": ["sparkle-id"], "🗓": ["calendar-id"],
                "✅": ["check-id"], "❌": ["cross-id"], "✖️": ["cross-id"],
            }
            markup = bot.ReplyKeyboardMarkup(
                keyboard=[[bot.KeyboardButton(text="🗓 Экономический календарь")]],
                resize_keyboard=True,
            )
            bot.apply_custom_button_icons(markup)
            button = markup.keyboard[0][0]
            self.assertEqual(button.icon_custom_emoji_id, "calendar-id")
            self.assertEqual(button.text, "Экономический календарь")
            rendered = bot.render_custom_emojis("🤖 ✅ 🗓 🧾 🅰️ QUANTUM TRADE AI")
            self.assertIn('emoji-id="robot-id"', rendered)
            self.assertIn('emoji-id="check-id"', rendered)
            self.assertIn('emoji-id="calendar-id"', rendered)
            self.assertIn("🧾", rendered)
            self.assertIn("🅰️", rendered)
            self.assertEqual(bot.render_custom_emojis("⏳"), "⏳")
            self.assertIn('emoji-id="cross-id"', bot.render_custom_emojis("❌"))
            self.assertIn("🛡 QUANTUM TRADE AI", rendered)
            status_id = bot.next_custom_emoji_id("❌")
            self.assertEqual(bot.next_custom_emoji_id("❌"), status_id)
        finally:
            bot._CUSTOM_EMOJI_PACK = old_pack

    async def test_main_keyboard_hides_removed_statistics_history_and_app_buttons(self):
        labels = [button.text for row in bot.main_keyboard.keyboard for button in row]
        self.assertNotIn("📊 СТАТИСТИКА", labels)
        self.assertNotIn("🕘 ИСТОРИЯ СИГНАЛОВ", labels)
        self.assertFalse(any("ОТКРЫТЬ ПРИЛОЖЕНИЕ" in label for label in labels))
        self.assertFalse(any("МОИ СИГНАЛЫ" in label for label in labels))
        self.assertFalse(hasattr(bot, "my_signals_handler"))

    async def test_removed_main_menu_buttons_stay_hidden_with_mini_app_url(self):
        labels = [
            button.text
            for row in bot.build_main_keyboard("https://mini.example.com").keyboard
            for button in row
        ]
        self.assertFalse(any("ОТКРЫТЬ ПРИЛОЖЕНИЕ" in label for label in labels))
        self.assertNotIn("📊 СТАТИСТИКА", labels)
        self.assertNotIn("🕘 ИСТОРИЯ СИГНАЛОВ", labels)


if __name__ == "__main__":
    unittest.main()
