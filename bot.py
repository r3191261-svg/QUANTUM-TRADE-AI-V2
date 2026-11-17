import asyncio
import copy
import html
import logging
import os
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

import aiohttp
import feedparser

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    FSInputFile,
    ErrorEvent,
)
from aiogram.exceptions import TelegramAPIError, TelegramConflictError, TelegramBadRequest
from aiogram.client.session.middlewares.base import BaseRequestMiddleware


# =========================================================
# QUANTUM TRADE AI — CONFIGURATION
# =========================================================

def load_local_env():
    """Load a local .env file without replacing explicitly supplied variables."""
    env_file = Path(__file__).resolve().with_name(".env")
    try:
        lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key or os.getenv(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


load_local_env()

TOKEN_USER = os.getenv("TOKEN_USER", "").strip()
TOKEN_ADMIN = os.getenv("TOKEN_ADMIN", "").strip()

def env_id(name, fallback):
    value = os.getenv(name, "").strip()
    return int(value) if value else fallback

OWNER_ID = env_id("OWNER_ID", 770710937)
DEFAULT_ADMIN_ID = env_id("DEFAULT_ADMIN_ID", 5232049751)
EXTRA_ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit() and int(value.strip()) > 0
}

# Numeric ID of the source Telegram channel.
SOURCE_CHANNEL_ID = -1003979525371
CRYPTO_PAIRS = (
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "TRX/USDT", "TON/USDT", "AVAX/USDT",
    "DOT/USDT", "LINK/USDT", "LTC/USDT", "BCH/USDT", "ETC/USDT",
    "XLM/USDT", "NEAR/USDT", "SUI/USDT", "APT/USDT", "FIL/USDT",
)
TRACKED_BINARY_PAIRS = (
    "EUR/USD", "AUD/USD", "USD/CHF", "EUR/GBP", "EUR/AUD", "EUR/CHF",
    "GBP/CHF", "AUD/CHF", "GBP/AUD", "USD/JPY", "EUR/JPY", "AUD/JPY",
    "GBP/JPY", "BTC/USD",
)
NEWS_RSS_URL = os.getenv("NEWS_RSS_URL", "").strip() or "https://www.investing.com/rss/news.rss"
NEWS_POLL_SECONDS = max(60, int(os.getenv("NEWS_POLL_SECONDS", "").strip() or "300"))
NEWS_LIMIT = 100
NEWS_REPUBLISH_ALLOWED = os.getenv("NEWS_REPUBLISH_ALLOWED", "false").strip().lower() == "true"
AUTOTRADE_DRAFT = "Здравствуйте! 🤝 Хочу подключить автоторговлю!"
SUPPORT_URL = "https://t.me/copy_broker_BO_bot?text=" + quote(AUTOTRADE_DRAFT)
REGISTRATION_URL = "https://clck.ru/3X2xAM"
BINODEX_REGISTRATION_URL = "https://bdclick.app/smart/DLreJY"
LOCAL_TZ = timezone(timedelta(hours=5), "Asia/Tashkent")

# ISO 4217 currency codes plus commonly quoted crypto tickers. Signals are
# counted only when a recognizable pair is actually present in a source post.
PAIR_CODES = set("AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XAG XAU XCD XCG XDR XOF XPD XPF XPT YER ZAR ZMW ZWL BTC ETH USDT USDC TON SOL XRP DOGE BNB ADA TRX DOT LTC BCH AVAX".split())
PAIR_CODE_PATTERN = "|".join(re.escape(code) for code in sorted(PAIR_CODES, key=len, reverse=True))
PAIR_RE = re.compile(
    rf"(?<![A-Z0-9])(?P<base>{PAIR_CODE_PATTERN})\s*[/_-]?\s*(?P<quote>{PAIR_CODE_PATTERN})(?![A-Z0-9])",
    re.I,
)

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().with_name("quantum.db")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
INTRO_GIF_PATH = os.getenv("INTRO_GIF_PATH", "assets/quantum_trade_ai_intro.gif")
INTRO_GIF_FILE_ID = os.getenv("INTRO_GIF_FILE_ID", "").strip()
INTRO_VIDEO_PATH = os.getenv("INTRO_VIDEO_PATH", "assets/quantum_trade_ai_promo.mp4")
DEFAULT_CUSTOM_EMOJI_PACKS = (
    "svoy_v_alfe,AR_PREMIUM,TrendsEmoji,zholto_rozovij,NewsEmoji,FlagsByKoylli,tgiosicons"
)
CUSTOM_EMOJI_PACK_NAMES = tuple(
    name.strip()
    for name in os.getenv("CUSTOM_EMOJI_PACK_NAMES", DEFAULT_CUSTOM_EMOJI_PACKS).split(",")
    if name.strip()
)
_CUSTOM_EMOJI_PACK = None
ANIMATED_EMOJI_TARGETS = (
    "🗓", "📅", "🕘", "🕒", "🤖", "➡️", "🇷🇺", "🇬🇧", "✏️", "🗞", "🛜", "📈", "📊",
    "🔔", "✅", "❌", "⌛", "🔕", "⚙️", "🛡", "📝", "📨", "📢", "🚫", "👤",
)
BUTTON_EMOJI_TARGETS = tuple(dict.fromkeys((*ANIMATED_EMOJI_TARGETS, "👤")))
ANIMATED_EMOJI_ALIASES = {
    "🤖": ("👾",),
    "🕒": ("🕘", "🕐", "⏰", "⌚"),
    "🕘": ("🕒", "🕐", "⏰", "⌚"),
    "✅": ("☑️", "✔️", "✔", "✓", "🗸"),
    "❌": ("✖️", "✖", "❎"),
    "⏳": ("⌛", "🕒", "⏰"),
    "👤": ("🧑", "🧑‍💼", "👨", "👩"),
    "🛡": ("🛡️",),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("QUANTUM_TRADE_AI")

user_dp = Dispatcher(storage=MemoryStorage())
admin_dp = Dispatcher()


class SupportRequest(StatesGroup):
    waiting_text = State()

# Set in main(); admin handlers use this bot to deliver user broadcasts.
USER_BOT: Bot | None = None
ADMIN_BOT: Bot | None = None
_POSTGRES_POOL = None
_POSTGRES_POOL_LOCK = threading.Lock()


@user_dp.errors()
async def user_dispatcher_error(event: ErrorEvent):
    record_runtime_error("user_bot_handler", event.exception)
    return True


@admin_dp.errors()
async def admin_dispatcher_error(event: ErrorEvent):
    record_runtime_error("admin_bot_handler", event.exception)
    return True


# =========================================================
# DATABASE
# =========================================================

class PostgresConnection:
    """Small SQLite-compatible adapter for the bot's managed PostgreSQL mode."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        if statement.startswith("PRAGMA table_info("):
            table = statement.removeprefix("PRAGMA table_info(").split(")", 1)[0]
            try:
                return self.connection.execute(
                    "SELECT ordinal_position - 1 AS cid, column_name AS name "
                    "FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=%s "
                    "ORDER BY ordinal_position",
                    (table,),
                )
            except Exception as error:
                raise sqlite3.Error(str(error)) from error

        sql = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        ignore_insert = "INSERT OR IGNORE" in sql.upper()
        sql = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", sql, flags=re.IGNORECASE)
        sql = sql.replace("?", "%s")
        if ignore_insert:
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        try:
            return self.connection.execute(sql, parameters)
        except Exception as error:
            try:
                import psycopg
                if isinstance(error, psycopg.IntegrityError):
                    raise sqlite3.IntegrityError(str(error)) from error
                if isinstance(error, psycopg.Error):
                    raise sqlite3.Error(str(error)) from error
            except ImportError:
                pass
            raise

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


@contextmanager
def connect_db():
    if DATABASE_URL:
        global _POSTGRES_POOL
        if _POSTGRES_POOL is None:
            with _POSTGRES_POOL_LOCK:
                if _POSTGRES_POOL is None:
                    from psycopg_pool import ConnectionPool
                    _POSTGRES_POOL = ConnectionPool(
                        conninfo=DATABASE_URL,
                        min_size=1,
                        max_size=10,
                        timeout=8,
                        kwargs={"connect_timeout": 5},
                        open=True,
                    )
        # Reuse warm connections instead of opening a new TLS/Postgres
        # connection for every button press and user update.
        conn = PostgresConnection(_POSTGRES_POOL.getconn())
        release = _POSTGRES_POOL.putconn
    else:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        release = None
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if release:
            release(conn.connection)
        else:
            conn.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def set_health(component, status, details=""):
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO bot_health (component, status, last_seen, details) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(component) DO UPDATE SET "
            "status=excluded.status, last_seen=excluded.last_seen, details=excluded.details",
            (component, status, now(), str(details)[:500]),
        )


def record_runtime_error(component, error):
    description = str(error).strip() or error.__class__.__name__
    log.error("%s: %s", component, description)
    try:
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO runtime_errors (component, description, created_at) "
                "VALUES (?, ?, ?)",
                (component[:80], description[:1000], now()),
            )
    except Exception:
        log.exception("Could not persist runtime error")


def record_delivery(source_message_id, user_id, status, error=""):
    try:
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO delivery_events "
                "(source_message_id, user_id, status, error, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_message_id, user_id, status, str(error)[:500], now()),
            )
    except Exception:
        log.exception("Could not persist message delivery metrics")


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                notifications INTEGER DEFAULT 1,
                language TEXT DEFAULT 'ru',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument TEXT,
                direction TEXT,
                timeframe TEXT,
                details TEXT,
                created_at TEXT,
                created_by BIGINT,
                source_message_id BIGINT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id BIGINT,
                action TEXT,
                target_id BIGINT,
                created_at TEXT
            )
        """)
        # Keeps source-channel post IDs to prevent duplicate broadcasts.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_posts (
                message_id BIGINT PRIMARY KEY,
                text TEXT DEFAULT '',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_deliveries (
                source_message_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                copied_message_id BIGINT,
                PRIMARY KEY (source_message_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_actions (
                action_key TEXT PRIMARY KEY,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_health (
                component TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                details TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delivery_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_message_id BIGINT,
                user_id BIGINT,
                status TEXT NOT NULL,
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                url TEXT NOT NULL,
                image_url TEXT DEFAULT '',
                published_at TEXT,
                fetched_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_posts_created_at ON source_posts(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at)")
        if DATABASE_URL:
            # Telegram IDs exceed PostgreSQL's 32-bit INTEGER range. Upgrade
            # projects created by earlier versions before inserting admin IDs.
            for table, column in (
                ("users", "user_id"), ("admins", "user_id"),
                ("signals", "created_by"), ("audit", "actor_id"),
                ("audit", "target_id"), ("source_posts", "message_id"),
                ("source_deliveries", "source_message_id"),
                ("source_deliveries", "user_id"),
                ("source_deliveries", "copied_message_id"),
            ):
                conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT")
        source_columns = {row[1] for row in conn.execute("PRAGMA table_info(source_posts)").fetchall()}
        if "updated_at" not in source_columns:
            conn.execute("ALTER TABLE source_posts ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE source_posts SET updated_at=created_at WHERE updated_at IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_posts_updated_at ON source_posts(updated_at)")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "signals_consent" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN signals_consent INTEGER DEFAULT -1")
        if "intro_sent" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN intro_sent INTEGER DEFAULT 0")
        if "favorite_pairs" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN favorite_pairs TEXT DEFAULT ''")
        if "market" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN market TEXT DEFAULT 'all'")
        if "timeframe" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN timeframe TEXT DEFAULT '5m'")
        signal_columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
        if "source_message_id" not in signal_columns:
            conn.execute("ALTER TABLE signals ADD COLUMN source_message_id BIGINT")
        for admin_id in {OWNER_ID, DEFAULT_ADMIN_ID, *EXTRA_ADMIN_IDS}:
            if admin_id > 0:
                conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))


def register_user(user):
    with connect_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users
            (user_id, username, full_name, status,
             notifications, language, created_at)
            VALUES (?, ?, ?, 'active', 1, 'ru', ?)
        """, (
            user.id,
            user.username or "",
            user.full_name or "",
            now(),
        ))
        conn.execute("""
            UPDATE users
            SET username=?, full_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.full_name or "",
            user.id,
        ))
        return conn.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()


def get_user(user_id):
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()


def get_status(user_id):
    user = get_user(user_id)
    return user[3] if user else "active"


def set_status(user_id, status):
    with connect_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, status, created_at)
            VALUES (?, ?, ?)
        """, (user_id, status, now()))
        conn.execute(
            "UPDATE users SET status=? WHERE user_id=?",
            (status, user_id),
        )


def is_admin(user_id):
    if user_id == OWNER_ID or user_id in EXTRA_ADMIN_IDS:
        return True
    with connect_db() as conn:
        result = conn.execute(
            "SELECT 1 FROM admins WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return result is not None


def audit(actor, action, target=None):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO audit (actor_id, action, target_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (actor, action, target, now()))


def extract_pairs(text):
    """Return only recognized quote pairs mentioned in real source text."""
    pairs = set()
    for match in PAIR_RE.finditer((text or "").upper()):
        base, quote = match.group("base"), match.group("quote")
        if base in PAIR_CODES and quote in PAIR_CODES and base != quote:
            pairs.add(f"{base}/{quote}")
    return pairs


def clean_feed_text(value):
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    value = re.sub(r"</p\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def feed_entry_image(entry):
    for item in (getattr(entry, "media_content", None) or []):
        url = item.get("url")
        if url and url.startswith("https://"):
            return url
    for item in (getattr(entry, "media_thumbnail", None) or []):
        url = item.get("url")
        if url and url.startswith("https://"):
            return url
    for item in (getattr(entry, "enclosures", None) or []):
        url = item.get("href") or item.get("url")
        if url and (item.get("type", "").startswith("image/") or re.search(r"\.(?:png|jpe?g|webp)(?:\?|$)", url, re.I)):
            return url
    html_content = " ".join([getattr(entry, "summary", "") or ""] + [
        item.get("value", "") for item in (getattr(entry, "content", None) or [])
    ])
    match = re.search(r'<img\b[^>]*\bsrc=["\'](https://[^"\']+)', html_content, re.I)
    return match.group(1) if match else ""


async def fetch_and_store_news():
    """Read Investing.com's published RSS feed and persist deduplicated items."""
    if not NEWS_REPUBLISH_ALLOWED:
        log.info("RSS ingestion disabled until redistribution rights are confirmed/configured.")
        return 0
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"User-Agent": "QUANTUM-TRADE-AI/2.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(NEWS_RSS_URL, allow_redirects=True) as response:
                response.raise_for_status()
                payload = await response.read()
        parsed = feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid RSS feed: {parsed.bozo_exception}")
        inserted = 0
        for entry in parsed.entries[:NEWS_LIMIT]:
            title = clean_feed_text(getattr(entry, "title", ""))
            url = (getattr(entry, "link", "") or "").strip()
            source_key = (getattr(entry, "id", "") or url).strip()
            if not title or not url.startswith("https://") or not source_key:
                continue
            raw_description = getattr(entry, "summary", "") or ""
            if not raw_description and getattr(entry, "content", None):
                raw_description = entry.content[0].get("value", "")
            description = clean_feed_text(raw_description)[:1800]
            published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            published_at = datetime(*published[:6], tzinfo=timezone.utc).isoformat() if published else None
            with connect_db() as conn:
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO news
                    (source_key, title, description, url, image_url, published_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (source_key, title, description, url, feed_entry_image(entry), published_at, now()))
                inserted += cursor.rowcount
        log.info("Investing.com RSS refresh finished; new items=%s", inserted)
        return inserted
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        log.warning("Could not refresh Investing.com RSS: %s", error)
    except Exception:
        log.exception("Unexpected error while reading Investing.com RSS")
    return 0


# =========================================================
# KEYBOARDS
# =========================================================

# User menu.
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📈 СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ", style="primary")],
        [KeyboardButton(text="🗓 ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ", style="success")],
        [
            KeyboardButton(text="📊 СТАТИСТИКА", style="danger"),
            KeyboardButton(text="🕘 ИСТОРИЯ СИГНАЛОВ", style="danger"),
        ],
        [KeyboardButton(text="🤖 АВТОМАТИЧЕСКИЙ БОТ", style="primary")],
        [KeyboardButton(text="🔔 УВЕДОМЛЕНИЯ", style="success")],
        [
            KeyboardButton(text="👤 МОЙ ПРОФИЛЬ", style="success"),
        ],
    ],
    resize_keyboard=True,
)


def colored_button(text, callback_data, style="primary"):
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


def signal_action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➡️ Регистрация у брокера",
            callback_data="choose_broker_signal",
            style="success",
        )],
        [InlineKeyboardButton(
            text="➡️ Подключить автоторговлю",
            url=SUPPORT_URL,
            style="success",
        )],
    ])


def broker_choice_keyboard(back_callback="broker_back_autotrade"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="INTRADE BAR", url=REGISTRATION_URL, style="success")],
        [InlineKeyboardButton(text="BinoDex", url=BINODEX_REGISTRATION_URL, style="success")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback, style="primary")],
    ])


def autotrade_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➡️ Регистрация у брокера",
            callback_data="choose_broker",
            style="success",
        )],
        [InlineKeyboardButton(
            text="➡️ Подключить автоторговлю",
            style="success",
            url=SUPPORT_URL,
        )],
    ])


def settings_keyboard(enabled):
    notification_text = "🔔 Уведомления: ВКЛ" if enabled else "🔕 Уведомления: ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button(notification_text, "toggle_notifications", "primary")],
        [
            colored_button("🇷🇺 Русский", "lang_ru", "primary"),
            colored_button("🇬🇧 English", "lang_en", "primary"),
        ],
        [colored_button("👤 Мой профиль", "profile", "primary")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("📊 Статистика", "admin_stats", "primary")],
        [colored_button("👤 Пользователи", "admin_users", "primary")],
        [colored_button("✏️ Управление сигналами", "admin_signals", "primary")],
        [colored_button("📢 Рассылка", "admin_broadcast", "primary")],
        [colored_button("🚫 Блокировки", "admin_blocks", "danger")],
        [colored_button("🛡 Администраторы", "admin_manage", "primary")],
        [colored_button("🗞 Журнал действий", "admin_audit", "primary")],
        [colored_button("🛜 Мониторинг", "admin_health", "success")],
        [colored_button("⚙️ Настройки бота", "admin_settings", "primary")],
    ])


def admin_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("↩️ К панели администратора", "admin_home", "primary")]
    ])


def admin_health_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("🛜 Состояние ботов", "admin_health_status", "success")],
        [colored_button("📨 Последний сигнал", "admin_health_signal", "primary")],
        [colored_button("⚠️ Последние ошибки", "admin_health_errors", "danger")],
        [colored_button("📬 Доставка сообщений", "admin_health_delivery", "primary")],
        [colored_button("↩️ К панели администратора", "admin_home", "primary")],
    ])


# =========================================================
# ACCESS CHECKS
# =========================================================

async def check_user(message):
    if not message.from_user:
        return False

    user = register_user(message.from_user)
    if user and user[3] in ("blocked", "suspended"):
        await message.answer(
            "⛔ Доступ временно ограничен.\nОбратитесь в поддержку."
        )
        return False

    return True


async def check_admin(message):
    if not message.from_user:
        return False
    if not is_admin(message.from_user.id):
        await message.answer(
            "⛔ Нет прав администратора.\n"
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
            "Передайте его владельцу для добавления в настройки бота."
        )
        return False
    return True


async def check_owner(message):
    if not message.from_user:
        return False
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Команда доступна только владельцу.")
        return False
    return True


# =========================================================
# USER START AND MAIN MENU
# =========================================================

async def show_main_menu(message):
    await message.answer(
        "🛡 QUANTUM TRADE AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Добро пожаловать в интеллектуальную торговую платформу!\n\n"
        "📈 Сигналы для бинарных опционов\n"
        "📅 Экономический календарь\n"
        "📊 Торговая статистика\n"
        "🕘 История сигналов\n"
        "🤖 Автоматическая торговля\n"
        "👤 Личный кабинет\n"
        "⚙️ Персональные настройки\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard,
    )


@user_dp.message(Command("start"))
async def start_handler(message: Message):
    if not message.from_user:
        return

    user = register_user(message.from_user)
    if user and user[3] in ("blocked", "suspended"):
        await message.answer("⛔ Доступ временно ограничен.\nОбратитесь в поддержку.")
        return

    consent = user[7] if user and len(user) > 7 else -1

    welcome_emoji = await custom_emoji_markup(message.bot, "🤖")
    welcome_text = (
        "🛡 <b>QUANTUM TRADE AI</b>\n\n"
        f"{welcome_emoji} <b>Добро пожаловать в мир интеллектуальной торговли!</b>\n\n"
        "Мы анализируем рынок за вас, используя современные алгоритмы "
        "искусственного интеллекта, чтобы помочь вам принимать более "
        "взвешенные торговые решения."
    )
    if consent in (0, 1):
        welcome_text += "\n\n<b>Выберите нужный раздел в меню.</b>"
        keyboard = main_keyboard
    else:
        welcome_text += (
            "\n\n📊 <b>Хотите получать торговые сигналы и следить за "
            "возможностями рынка вместе с QUANTUM TRADE AI?</b>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [colored_button("✅ ПРИНЯТЬ", "signals_accept", "success")],
            [colored_button("❌ ОТКЛОНИТЬ", "signals_decline", "danger")],
        ])

    # Send the supplied promo clip with every /start greeting. Fall back to
    # the original GIF if the MP4 asset is unavailable in the deployment.
    video = FSInputFile(INTRO_VIDEO_PATH) if os.path.isfile(INTRO_VIDEO_PATH) else None
    animation = INTRO_GIF_FILE_ID or (
        FSInputFile(INTRO_GIF_PATH) if os.path.isfile(INTRO_GIF_PATH) else None
    )
    try:
        if video:
            await message.answer_video(video, caption=welcome_text, reply_markup=keyboard)
        elif animation:
            await message.answer_animation(animation, caption=welcome_text, reply_markup=keyboard)
        else:
            await message.answer(welcome_text, reply_markup=keyboard)
    except TelegramAPIError:
        log.exception("Could not send welcome video; using text greeting")
        await message.answer(welcome_text, reply_markup=keyboard)


async def custom_emoji_markup(bot, fallback_emoji):
    """Use an exact animated emoji from the configured packs, if available."""
    global _CUSTOM_EMOJI_PACK
    if _CUSTOM_EMOJI_PACK is None:
        await setup_custom_emojis(bot)
    custom_id = next_custom_emoji_id(fallback_emoji)
    if not custom_id:
        custom_id = next((
            custom_id
            for alias in ANIMATED_EMOJI_ALIASES.get(fallback_emoji, ())
            for custom_id in (_CUSTOM_EMOJI_PACK or {}).get(alias, ())
        ), None)
    return custom_emoji_entity(fallback_emoji, custom_id) if custom_id else fallback_emoji


def is_single_emoji_fallback(value):
    """Reject pack entries whose alt text is a letter or multiple separate emoji."""
    if not value or any(char.isalpha() or char.isspace() for char in value):
        return False
    if re.fullmatch(r"[#*0-9]\ufe0f?\u20e3", value):
        return True

    codepoints = [ord(char) for char in value]
    regional = [cp for cp in codepoints if 0x1F1E6 <= cp <= 0x1F1FF]
    if regional:
        return len(regional) == 2 and len(regional) == len(codepoints)

    bases = [
        char for char in value
        if unicodedata.category(char) == "So" and not (0x1F3FB <= ord(char) <= 0x1F3FF)
    ]
    allowed = all(
        unicodedata.category(char) == "So"
        or 0x1F3FB <= ord(char) <= 0x1F3FF
        or ord(char) in {0x200D, 0xFE0E, 0xFE0F, 0x20E3}
        or 0xE0020 <= ord(char) <= 0xE007F
        for char in value
    )
    if not allowed or not bases:
        return False
    # A ZWJ sequence is one composed sticker; separate adjacent symbols are rejected.
    joiners = codepoints.count(0x200D)
    return len(bases) == 1 if not joiners else len(bases) == joiners + 1


def remove_emoji_characters(text):
    """Remove static or unsupported emoji glyphs; animated custom emoji are added separately."""
    text = re.sub(r"[#*0-9]\ufe0f?\u20e3", "", text)
    output = []
    for char in text:
        cp = ord(char)
        is_emoji_symbol = unicodedata.category(char) == "So" or 0x1F3FB <= cp <= 0x1F3FF
        is_emoji_joiner = cp in {0x200D, 0xFE0E, 0xFE0F, 0x20E3} or 0xE0020 <= cp <= 0xE007F
        if not is_emoji_symbol and not is_emoji_joiner:
            output.append(char)
    return "".join(output)


async def setup_custom_emojis(bot):
    """Load the configured emoji pack and install outgoing message decoration."""
    global _CUSTOM_EMOJI_PACK
    middleware_manager = getattr(getattr(bot, "session", None), "middleware", None)
    if middleware_manager is not None and not any(
        isinstance(item, CustomEmojiRequestMiddleware) for item in middleware_manager
    ):
        middleware_manager.register(CustomEmojiRequestMiddleware())
    if _CUSTOM_EMOJI_PACK is not None:
        return
    _CUSTOM_EMOJI_PACK = {}
    get_sticker_set = getattr(bot, "get_sticker_set", None)
    if not callable(get_sticker_set):
        return
    for pack_name in CUSTOM_EMOJI_PACK_NAMES:
        try:
            sticker_set = await get_sticker_set(pack_name)
            pack_count = 0
            for sticker in sticker_set.stickers:
                custom_id = getattr(sticker, "custom_emoji_id", None)
                emoji = sticker.emoji or ""
                is_animated = bool(
                    getattr(sticker, "is_animated", False)
                    or getattr(sticker, "is_video", False)
                )
                if custom_id and is_animated and is_single_emoji_fallback(emoji):
                    _CUSTOM_EMOJI_PACK.setdefault(emoji, []).append(custom_id)
                    pack_count += 1
            log.info("Loaded %d custom emojis from %s", pack_count, pack_name)
        except Exception:
            log.exception("Could not load custom emoji pack %s", pack_name)
    log.info("Loaded custom emoji mappings for %d distinct symbols", len(_CUSTOM_EMOJI_PACK))


def next_custom_emoji_id(emoji):
    """Return an exact sticker match; never substitute an unrelated sticker."""
    sticker_ids = (_CUSTOM_EMOJI_PACK or {}).get(emoji, ())
    if not sticker_ids:
        sticker_ids = next((
            (_CUSTOM_EMOJI_PACK or {}).get(alias, ())
            for alias in ANIMATED_EMOJI_ALIASES.get(emoji, ())
            if (_CUSTOM_EMOJI_PACK or {}).get(alias)
        ), ())
    return sticker_ids[0] if sticker_ids else None


def render_custom_emojis(text):
    """Replace exact pack matches with their animated Telegram custom emoji."""
    if not text or not _CUSTOM_EMOJI_PACK:
        return text
    protected = []

    def protect(match):
        protected.append(match.group(0))
        return f"\x00CUSTOM_EMOJI_{len(protected) - 1}\x00"

    text = re.sub(r"<tg-emoji\b[^>]*>.*?</tg-emoji>", protect, text, flags=re.S)
    text = re.sub(r"(?<!🛡 )QUANTUM TRADE AI", "🛡 QUANTUM TRADE AI", text)
    emoji_map = {
        emoji: (next_custom_emoji_id(emoji),)
        for emoji in ANIMATED_EMOJI_TARGETS
        if next_custom_emoji_id(emoji)
    }
    if emoji_map:
        pattern = re.compile("|".join(re.escape(item) for item in sorted(emoji_map, key=len, reverse=True)))
        text = pattern.sub(
            lambda match: custom_emoji_entity(match.group(0), next_custom_emoji_id(match.group(0))),
            text,
        )
    for index, block in enumerate(protected):
        text = text.replace(f"\x00CUSTOM_EMOJI_{index}\x00", block)
    return text


def custom_emoji_entity(emoji, custom_id):
    if not custom_id:
        return html.escape(emoji)
    return f'<tg-emoji emoji-id="{custom_id}">{html.escape(emoji)}</tg-emoji>'


RU_EN_TRANSLATIONS = {
    "📈 СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ": "BINARY OPTION SIGNALS",
    "СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ": "BINARY OPTION SIGNALS",
    "Сигналы для бинарных опционов": "Binary option signals",
    "🗓 ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ": "ECONOMIC CALENDAR",
    "📅 ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ": "ECONOMIC CALENDAR",
    "ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ": "ECONOMIC CALENDAR",
    "Экономический календарь": "Economic calendar",
    "СТАТИСТИКА ЗА ПОСЛЕДНИЕ 24 ЧАСА": "RESULTS FOR THE LAST 24 HOURS",
    "РЕЗУЛЬТАТЫ ЗА ПОСЛЕДНИЕ 24 ЧАСА": "RESULTS FOR THE LAST 24 HOURS",
    "СТАТИСТИКА": "STATISTICS",
    "Статистика": "Statistics",
    "ИСТОРИЯ СИГНАЛОВ ЗА 24 ЧАСА": "SIGNAL HISTORY — LAST 24 HOURS",
    "🕘 ИСТОРИЯ СИГНАЛОВ": "SIGNAL HISTORY",
    "ИСТОРИЯ СИГНАЛОВ": "SIGNAL HISTORY",
    "История сигналов": "Signal history",
    "🤖 АВТОМАТИЧЕСКИЙ БОТ": "AUTOMATED TRADING BOT",
    "АВТОМАТИЧЕСКИЙ БОТ": "AUTOMATED TRADING BOT",
    "Автоматический бот": "Automated trading bot",
    "Подключить автоторговлю": "Connect automated trading",
    "Регистрация у брокера": "Broker registration",
    "МОИ СИГНАЛЫ": "MY SIGNALS",
    "Мои сигналы": "My signals",
    "Последние опубликованные сигналы": "Latest published signals",
    "Сигналов с выбранными парами и интервалом пока нет.": "No signals for the selected pairs and interval yet.",
    "Сигналов пока нет.": "No signals yet.",
    "🔔 УВЕДОМЛЕНИЯ": "NOTIFICATIONS",
    "УВЕДОМЛЕНИЯ": "NOTIFICATIONS",
    "Уведомления": "Notifications",
    "Оповещения о новых сигналах включены.": "New signal alerts are enabled.",
    "Оповещения о новых сигналах выключены.": "New signal alerts are disabled.",
    "📃 МОЙ ПРОФИЛЬ": "MY PROFILE",
    "👤 МОЙ ПРОФИЛЬ": "MY PROFILE",
    "МОЙ ПРОФИЛЬ": "MY PROFILE",
    "Мой профиль": "My profile",
    "ЛИЧНЫЙ КАБИНЕТ": "MY ACCOUNT",
    "Имя": "Name",
    "Статус": "Status",
    "АКТИВЕН": "ACTIVE",
    "НЕАКТИВЕН": "INACTIVE",
    "Выберите нужный раздел в меню.": "Choose a section from the menu.",
    "Выберите нужный раздел:": "Choose a section:",
    "ВЫБЕРИТЕ ДЕЙСТВИЕ:": "CHOOSE AN ACTION:",
    "История сигналов пока пуста.": "Signal history is empty.",
    "Сигналов за сутки": "Signals in the last 24 hours",
    "Профиль": "Profile",
    "Пользователь": "User",
    "Бинарные опционы": "Binary options",
    "Календарь макроэкономических событий: время, страна, важность, фактическое значение и прогноз.": "Macroeconomic events calendar: time, country, importance, actual and forecast.",
    "Откройте официальный календарь по кнопке ниже.": "Open the economic calendar using the button below.",
    "Добро пожаловать в мир интеллектуальной торговли!": "Welcome to intelligent trading!",
    "Добро пожаловать в интеллектуальную торговую платформу!": "Welcome to the intelligent trading platform!",
    "Мы анализируем рынок за вас, используя современные алгоритмы искусственного интеллекта, чтобы помочь вам принимать более взвешенные торговые решения.": "We analyze the market using modern AI algorithms to help you make more informed trading decisions.",
    "Хотите получать торговые сигналы и следить за возможностями рынка вместе с QUANTUM TRADE AI?": "Would you like to receive trading signals and follow market opportunities with QUANTUM TRADE AI?",
    "ПРИНЯТЬ": "ACCEPT",
    "ОТКЛОНИТЬ": "DECLINE",
    "СИГНАЛЫ ВКЛЮЧЕНЫ": "SIGNALS ENABLED",
    "СИГНАЛЫ ОТКЛЮЧЕНЫ": "SIGNALS DISABLED",
    "Вы будете получать новые сигналы.": "You will receive new signals.",
    "Сигналы отправляться не будут.": "Signals will not be sent.",
    "Выбор сохранён": "Your choice has been saved",
    "Активных": "Active",
    "Заблокированных": "Blocked",
    "Всего пользователей": "Total users",
    "Пользователей пока нет.": "There are no users yet.",
    "Управление сигналами": "Manage signals",
    "Журнал действий": "Action log",
    "Мониторинг": "Monitoring",
    "Состояние ботов": "Bot status",
    "Последний сигнал": "Latest signal",
    "Последние ошибки": "Recent errors",
    "Доставка сообщений": "Message delivery",
    "К панели администратора": "Back to admin panel",
    "Назад": "Back",
    "Обновить": "Refresh",
    "Время": "Time",
    "Направление": "Direction",
    "Таймфрейм": "Timeframe",
    "Комментарий": "Comment",
    "Сигналов за сутки": "Signals in the last 24 hours",
    "ПРИБЫЛЬ": "PROFIT",
    "ВЫИГРЫШ": "WIN",
    "ПРОИГРЫШ": "LOSS",
    "Без текста": "No text",
    "История пары не найдена.": "No history found for this pair.",
    "Ожидаем сигналы в этом боте.": "Waiting for signals in this bot.",
    "Уведомления включены.": "Notifications enabled.",
    "Уведомления отключены.": "Notifications disabled.",
    "Сначала нажмите /start.": "Please press /start first.",
    "ПЕРСОНАЛЬНЫЕ НАСТРОЙКИ": "PREFERENCES",
    "Русский": "Russian",
    "Выберите нужный раздел.": "Choose a section.",
    "Сигналы и данные обновляются автоматически.": "Signals and data update automatically.",
    "К сигналам для бинарных опционов": "Back to binary option signals",
    "К списку пар": "Back to pairs",
    "Валютные пары": "Currency pairs",
    "сигнал(ов)": "signal(s)",
    "сигналов": "signals",
    "Далее": "Next",
    "Некорректная страница.": "Invalid page.",
    "Ожидаем сигналы в этом боте.": "Waiting for new signals.",
    "Сигналов с распознанными парами за этот период нет.": "No signals with recognized pairs were found for this period.",
    "Не удалось определить пару": "Pair could not be identified",
    "Распознанных сигналов": "Recognized signals",
    "Время сигналов": "Signal times",
    "последние сигналы": "latest signals",
    "История пары не найдена.": "No history found for this pair.",
    "НОВОСТИ": "NEWS",
    "Свежие новости": "Latest news",
    "Новость не найдена.": "News item not found.",
    "время не указано": "time unavailable",
    "Описание в RSS источником не предоставлено.": "No description was provided by the RSS source.",
    "Источник": "Source",
    "Открыть экономический календарь": "Open economic calendar",
    "РЕЗУЛЬТАТЫ ЗА ПОСЛЕДНИЕ 10 МИНУТ": "RESULTS FOR THE LAST 10 MINUTES",
    "СИГНАЛОВ ДЛЯ БИНАРНЫХ ОПЦИОНОВ": "BINARY OPTION SIGNALS",
    "ЛИЧНЫЙ КАБИНЕТ": "MY ACCOUNT",
    "Username": "Username",
    "не указан": "not specified",
    "Направление:": "Direction:",
    "Таймфрейм:": "Timeframe:",
    "Комментарий:": "Details:",
    "Оповещения о новых сигналах включены.": "New signal notifications are on.",
    "Оповещения о новых сигналах выключены.": "New signal notifications are off.",
    "Доступ ограничен.": "Access is restricted.",
    "Сигналы включены.": "Signals are enabled.",
    "Сигналы выключены.": "Signals are disabled.",
    "Главное меню QUANTUM TRADE AI": "QUANTUM TRADE AI main menu",
    "Аналитика валютного рынка": "FOREX MARKET ANALYSIS",
    "Анализ рынка": "Market analysis",
    "Торговые сигналы": "Trading signals",
    "Источник реальных котировок пока не подключён.": "A live price feed is not connected yet.",
    "Криптопары к USDT": "CRYPTO PAIRS AGAINST USDT",
    "В сохранённых публикациях пока не найдено сигналов с распознанными валютными парами.": "No signals with recognized currency pairs were found in saved posts.",
    "сигнал(ов)": "signal(s)",
    "сообщ.": "messages",
    "Без текста": "No text",
    "СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ": "BINARY OPTION SIGNALS",
    "СИГНАЛОВ ЗА ПОСЛЕДНИЕ 10 МИНУТ": "SIGNALS IN THE LAST 10 MINUTES",
    "Не удалось передать обращение: бот администратора сейчас недоступен. Попробуйте позже.": "Could not deliver your request: the admin bot is unavailable. Please try again later.",
    "Напишите вопрос одним сообщением — я передам его администратору.": "Send your question in one message and I will forward it to the administrator.",
    "Для отмены отправьте /cancel.": "Send /cancel to cancel.",
    "Обращение отменено.": "Request cancelled.",
    "Ваше сообщение передано администратору.": "Your message has been sent to the administrator.",
    "Не удалось передать обращение. Попробуйте отправить его ещё раз позже.": "Could not deliver your request. Please try again later.",
    "Пожалуйста, отправьте обращение текстом. Для отмены — /cancel.": "Please send your request as text. Send /cancel to cancel.",
    "Доступ временно ограничен.": "Access is temporarily restricted.",
    "Обратитесь в поддержку.": "Contact support.",
    "Выберите нужный раздел в меню.": "Choose a section from the menu.",
    "Ожидаю ваше сообщение.": "Waiting for your message.",
    "Выбор сохранён": "Your choice has been saved",
    "Язык интерфейса изменён на русский.": "Interface language changed to Russian.",
    "Календарь": "Calendar",
    "Открыть новости Investing.com": "Open Investing.com news",
    "Официальные RSS и условия": "Official RSS and terms",
    "Новости Investing.com · Сегодня": "Investing.com News · Today",
    "Лента доступна на официальном сайте.": "The news feed is available on the official website.",
    "Показ публикаций внутри бота включается только после подтверждения прав на хранение и повторное распространение RSS-материалов.": "Posts will appear in the bot only after permission to store and redistribute RSS content is confirmed.",
    "Сегодняшнем RSS-потоке пока нет публикаций.": "There are no posts in today's RSS feed yet.",
    "Нажмите «Обновить», чтобы получить свежую ленту.": "Tap Refresh to load the latest feed.",
    "Лента обновлена": "Feed refreshed",
    "Откройте официальный сайт Investing.com": "Open the official Investing.com website",
    "Новость не найдена.": "News item not found.",
    "Описание в RSS источником не предоставлено.": "The RSS source did not provide a description.",
    "время не указано источником": "time not provided by the source",
    "Ташкент": "Tashkent",
    "Открыть на Investing.com": "Open on Investing.com",
    "К сегодняшним новостям": "Back to today's news",
    "Откройте официальный календарь по кнопке ниже.": "Open the official calendar using the button below.",
    "Фактическое значение": "Actual",
    "Прогноз": "Forecast",
    "Выигрыш": "Win",
    "Проигрыш": "Loss",
    "активен": "active",
    "неактивен": "inactive",
    "Имя": "Name",
    "Пользователь": "User",
    "ID:": "ID:",
    "Источник": "Source",
    "Поддержка": "Support",
    "ВНИЗ": "DOWN",
    "ВВЕРХ": "UP",
    "вверх": "up",
    "вниз": "down",
    "Демо-анализ": "AI analysis",
    "СИГНАЛЫ ВКЛЮЧЕНЫ": "SIGNALS ENABLED",
    "СИГНАЛЫ ОТКЛЮЧЕНЫ": "SIGNALS DISABLED",
    "Вы будете получать новые сигналы.": "You will receive new signals.",
    "Сигналы отправляться не будут.": "Signals will not be sent.",
    "Главное меню QUANTUM TRADE AI": "QUANTUM TRADE AI main menu",
    "Статистика за последние 10 минут": "Statistics for the last 10 minutes",
    "СТАТИСТИКА ЗА ПОСЛЕДНИЕ 10 МИНУТ": "STATISTICS FOR THE LAST 10 MINUTES",
    "СТАТИСТИКА ЗА ПОСЛЕДНИЕ 24 ЧАСА": "STATISTICS FOR THE LAST 24 HOURS",
    "Статистика за последние 24 часа": "Statistics for the last 24 hours",
    "РЕЗУЛЬТАТЫ ЗА ПОСЛЕДНИЕ 24 ЧАСА": "RESULTS FOR THE LAST 24 HOURS",
    "Сигналов за сутки": "Signals in the last 24 hours",
    "История сигналов за 24 часа": "Signal history for the last 24 hours",
    "Календарь макроэкономических событий": "Macroeconomic events calendar",
    "Валютные пары": "Currency pairs",
    "Новости Investing.com": "Investing.com News",
    "Старее": "Older",
    "Новее": "Newer",
    "Обновить": "Refresh",
    "СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ": "BINARY OPTION SIGNALS",
    "управление сигналами": "signal management",
    "Пользователи": "Users",
    "Рассылка": "Broadcast",
    "Блокировки": "Blocks",
    "Администраторы": "Administrators",
    "Журнал действий": "Action log",
    "Мониторинг": "Monitoring",
    "Настройки бота": "Bot settings",
    "ПАНЕЛЬ УПРАВЛЕНИЯ": "ADMIN PANEL",
    "КОМАНДЫ АДМИНИСТРАТОРА": "ADMIN COMMANDS",
    "Последние пользователи": "Recent users",
    "Всего пользователей": "Total users",
    "Состояние ботов": "Bot status",
    "Последний сигнал": "Latest signal",
    "Последние ошибки": "Recent errors",
    "Доставка сообщений": "Message delivery",
    "Уведомления: ВКЛ": "Notifications: ON",
    "Уведомления: ВЫКЛ": "Notifications: OFF",
    "🔔 Уведомления: ВКЛ": "🔔 Notifications: ON",
    "🔕 Уведомления: ВЫКЛ": "🔕 Notifications: OFF",
    "Уведомления: Вкл": "Notifications: ON",
    "Уведомления: Выкл": "Notifications: OFF",
    "ID: ": "ID: ",
    "Имя: ": "Name: ",
    "Username: ": "Username: ",
    "Статус: ": "Status: ",
}


def translate_to_english(text):
    for russian, english in sorted(RU_EN_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(russian, english)
    return text


def localized_user_text(user_id, text):
    return translate_to_english(text) if chat_language(user_id) == "en" else text


def chat_language(chat_id):
    if not isinstance(chat_id, int) or chat_id <= 0:
        return "ru"
    try:
        with connect_db() as conn:
            row = conn.execute("SELECT language FROM users WHERE user_id=?", (chat_id,)).fetchone()
        return "en" if row and row[0] == "en" else "ru"
    except Exception:
        log.exception("Could not look up preferred language for chat %s", chat_id)
        return "ru"


def apply_custom_button_icons(reply_markup, language="ru"):
    """Use animated icons only for buttons with an exact match in the selected packs."""
    if not reply_markup:
        return
    keyboard = getattr(reply_markup, "inline_keyboard", None) or getattr(reply_markup, "keyboard", None)
    if not keyboard:
        return
    for row in keyboard:
        for button in row:
            label = getattr(button, "text", "") or ""
            if language == "en":
                label = translate_to_english(label)
            for emoji in sorted(BUTTON_EMOJI_TARGETS, key=len, reverse=True):
                if emoji and emoji in label and next_custom_emoji_id(emoji):
                    try:
                        button.icon_custom_emoji_id = next_custom_emoji_id(emoji)
                        button.text = label.replace(emoji, "", 1).lstrip()
                    except (AttributeError, TypeError, ValueError):
                        pass
                    break


class CustomEmojiRequestMiddleware(BaseRequestMiddleware):
    """Apply the configured premium emoji pack consistently to outgoing messages."""

    async def __call__(self, make_request, bot, method):
        language = chat_language(getattr(method, "chat_id", None))
        for field in ("text", "caption"):
            value = getattr(method, field, None)
            entities_field = "caption_entities" if field == "caption" else "entities"
            if (
                value
                and hasattr(method, "parse_mode")
                and getattr(method, "parse_mode", None) is not None
                and not getattr(method, entities_field, None)
            ):
                if language == "en":
                    value = translate_to_english(value)
                rendered = render_custom_emojis(value)
                # Telegram has no font-size control for bot messages. Use
                # bold as the consistent, readable text treatment requested.
                if "<code" not in rendered.lower() and "<pre" not in rendered.lower():
                    rendered = f"<b>{rendered}</b>"
                if rendered != getattr(method, field, None):
                    setattr(method, field, rendered)
                    method.parse_mode = ParseMode.HTML
        reply_markup = getattr(method, "reply_markup", None)
        if reply_markup:
            reply_markup = copy.deepcopy(reply_markup)
            method.reply_markup = reply_markup
        apply_custom_button_icons(reply_markup, language)
        return await make_request(bot, method)


@user_dp.callback_query(F.data.in_({"signals_accept", "signals_decline"}))
async def signal_consent_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return

    accepted = callback.data == "signals_accept"
    enabled = 1 if accepted else 0
    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET signals_consent=?, notifications=? WHERE user_id=?",
            (enabled, enabled, callback.from_user.id),
        )

    status = (
        "✅ <b>СИГНАЛЫ ВКЛЮЧЕНЫ</b>\nВы будете получать новые сигналы."
        if accepted else
        "⭕ <b>СИГНАЛЫ ОТКЛЮЧЕНЫ</b>\nСигналы отправляться не будут."
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(localized_user_text(callback.from_user.id, "Выбор сохранён"))
    await callback.message.answer(
        status + "\n\n💠 <b>Главное меню QUANTUM TRADE AI</b>",
        reply_markup=main_keyboard,
    )


# =========================================================
# LEGACY FOREX HANDLER — KEPT, NOT SHOWN IN NEW MENU
# =========================================================

@user_dp.message(F.text == "📊 FOREX")
async def forex_handler(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "📊 QUANTUM FOREX AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 АНАЛИТИКА ВАЛЮТНОГО РЫНКА\n\n"
        "💱 Валютные пары\n"
        "📈 Анализ рынка\n"
        "🎯 Торговые сигналы\n"
        "📊 Статистика\n\n"
        "🟡 Источник реальных котировок пока не подключён."
    )


# =========================================================
# BINARY OPTIONS
# =========================================================

@user_dp.message(Command("signals"))
@user_dp.message(F.text.in_({
    "📈 СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ",
    "СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ",
    "📈 Сигналы для бинарных опционов",
    "Сигналы для бинарных опционов",
    "BINARY OPTION SIGNALS",
    "⚡ БИНАРНЫЕ ОПЦИОНЫ",
    "⚡ Бинарные опционы",
}))
async def options_handler(message: Message):
    if not await check_user(message):
        return

    section_emoji = await custom_emoji_markup(message.bot, "📈")
    await message.answer(
        f"{section_emoji} <b>СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите нужный раздел.\n\nСигналы и данные обновляются автоматически.",
        reply_markup=binary_menu_keyboard(),
    )


def binary_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("📈 СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ", "binary_recent_10", "success")],
    ])


@user_dp.callback_query(F.data == "crypto_pairs")
async def crypto_pairs_handler(callback: CallbackQuery):
    lines = ["₿ <b>КРИПТОПАРЫ К USDT</b>", "━━━━━━━━━━━━━━━━━━"]
    lines.extend(f"{index}. <code>{pair}</code>" for index, pair in enumerate(CRYPTO_PAIRS, 1))
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [colored_button("⬅️ К сигналам для бинарных опционов", "binary_menu", "primary")],
        ]),
    )
    await callback.answer()


@user_dp.callback_query(F.data == "binary_all_pairs")
async def binary_all_pairs(callback: CallbackQuery):
    await show_pair_page(callback, 0)
    await callback.answer()


async def show_pair_page(callback: CallbackQuery, offset):
    pairs = {pair: {"count": 0, "last_id": None} for pair in TRACKED_BINARY_PAIRS}
    with connect_db() as conn:
        posts = conn.execute("SELECT message_id, text FROM source_posts ORDER BY created_at DESC").fetchall()
    for message_id, body in posts:
        for pair in extract_pairs(body):
            pairs.setdefault(pair, {"count": 0, "last_id": message_id})["count"] += 1
    if not pairs:
        await callback.message.edit_text(
            "💱 <b>ВАЛЮТНЫЕ ПАРЫ</b>\n\n"
            "В сохранённых публикациях пока не найдено сигналов с распознанными валютными парами.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [colored_button("⬅️ Назад", "binary_menu", "primary")]
            ]),
        )
        return
    ordered = sorted(pairs.items(), key=lambda item: (-item[1]["count"], item[0]))
    page_size = 20
    page = ordered[offset:offset + page_size]
    lines = [f"💱 <b>ВАЛЮТНЫЕ ПАРЫ</b> · {offset+1}–{offset+len(page)} из {len(ordered)}", "━━━━━━━━━━━━━━━━━━"]
    buttons = []
    for pair, values in page:
        lines.append(f"\n<b>{pair}</b> — {values['count']} сигнал(ов)")
        buttons.append([colored_button(f"{pair} · {values['count']}", f"pair:{pair}", "primary")])
    nav = []
    if offset > 0:
        nav.append(colored_button("⬅️ Назад", f"pairs_page:{max(0, offset-page_size)}", "primary"))
    if offset + page_size < len(ordered):
        nav.append(colored_button("Далее ➡️", f"pairs_page:{offset+page_size}", "primary"))
    if nav:
        buttons.append(nav)
    buttons.append([colored_button("⬅️ Назад", "binary_menu", "primary")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@user_dp.callback_query(F.data.startswith("pairs_page:"))
async def pair_page_callback(callback: CallbackQuery):
    try:
        offset = max(0, int(callback.data.split(":", 1)[1]))
    except ValueError:
        await callback.answer(localized_user_text(callback.from_user.id, "Некорректная страница."), show_alert=True)
        return
    await show_pair_page(callback, offset)
    await callback.answer()


@user_dp.callback_query(F.data == "binary_recent_10")
async def binary_recent_signals(callback: CallbackQuery):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with connect_db() as conn:
        posts = conn.execute(
            "SELECT message_id, text, created_at FROM source_posts WHERE created_at>=? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    counts = {}
    unknown = []
    total = 0
    for _, body, created_at in posts:
        pairs = extract_pairs(body)
        if not pairs:
            unknown.append(created_at)
            continue
        for pair in pairs:
            counts[pair] = counts.get(pair, 0) + 1
            total += 1
    if not posts:
        await callback.message.edit_text(
            "📈 <b>СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Ожидаем сигналы в этом боте.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [colored_button("🔄 Обновить", "binary_recent_10", "primary")],
                [colored_button("⬅️ Назад", "binary_menu", "primary")],
            ]),
        )
        await callback.answer()
        return

    lines = ["📊 <b>СТАТИСТИКА ЗА ПОСЛЕДНИЕ 10 МИНУТ</b>", "━━━━━━━━━━━━━━━━━━"]
    if counts:
        lines.extend(f"\n💱 <b>{pair}</b> — {count} сигнал(ов)" for pair, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    else:
        lines.append("\nСигналов с распознанными парами за этот период нет.")
    if unknown:
        lines.append(f"\n❔ Не удалось определить пару — {len(unknown)} сообщ.")
    lines.append(f"\n\n📨 Распознанных сигналов: {total}")
    lines.append("\nВремя сигналов (UTC):")
    for _, _, created_at in posts[:10]:
        lines.append(f"\n• {created_at[11:19]} UTC")
    await callback.message.edit_text(
        "".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [colored_button("🔄 Обновить", "binary_recent_10", "primary")],
            [colored_button("⬅️ Назад", "binary_menu", "primary")],
        ]),
    )
    await callback.answer()


@user_dp.callback_query(F.data.startswith("pair:"))
async def binary_pair_history(callback: CallbackQuery):
    pair = callback.data.split(":", 1)[1]
    with connect_db() as conn:
        posts = conn.execute("SELECT message_id, text, created_at FROM source_posts ORDER BY created_at DESC").fetchall()
    matched = [(body, created) for _, body, created in posts if pair in extract_pairs(body)][:10]
    lines = [f"💱 <b>{html.escape(pair)}</b> · последние сигналы", "━━━━━━━━━━━━━━━━━━"]
    for body, created in matched:
        excerpt = html.escape((body or "").strip()[:500])
        lines.append(f"\n{created[11:19]} UTC\n{excerpt or 'Без текста'}")
    if not matched:
        lines.append("\nИстория пары не найдена.")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [colored_button("⬅️ К списку пар", "binary_all_pairs", "primary")],
        ]),
    )
    await callback.answer()


@user_dp.callback_query(F.data == "binary_menu")
async def binary_menu(callback: CallbackQuery):
    section_emoji = await custom_emoji_markup(callback.bot, "📈")
    await callback.message.edit_text(
        f"{section_emoji} <b>СИГНАЛЫ ДЛЯ БИНАРНЫХ ОПЦИОНОВ</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите раздел.\n\nСигналы и данные обновляются автоматически.",
        reply_markup=binary_menu_keyboard(),
    )
    await callback.answer()


# =========================================================
# NEWS
# =========================================================

@user_dp.message(F.text.in_({"🌐 НОВОСТИ", "📰 Новости"}))
async def news_handler(message: Message):
    if not await check_user(message):
        return
    await fetch_and_store_news()
    await show_news_page(message, 0)


def today_news_rows(offset=0):
    local_midnight = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight.astimezone(timezone.utc).isoformat()
    with connect_db() as conn:
        return conn.execute("""
            SELECT id, title, description, url, image_url, published_at
            FROM news WHERE published_at>=?
            ORDER BY published_at DESC LIMIT 6 OFFSET ?
        """, (utc_midnight, offset)).fetchall()


async def show_news_page(target, offset):
    if not NEWS_REPUBLISH_ALLOWED:
        text = (
            "🌐 <b>НОВОСТИ INVESTING.COM</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "Лента доступна на официальном сайте. Показ публикаций внутри бота "
            "включается только после подтверждения прав на хранение и повторное распространение RSS-материалов."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↗️ Открыть новости Investing.com", url="https://ru.investing.com/news/", style="primary")],
            [InlineKeyboardButton(text="ℹ️ Официальные RSS и условия", url="https://www.investing.com/webmaster-tools/rss", style="primary")],
        ])
        if isinstance(target, Message):
            await target.answer(text, reply_markup=markup)
        else:
            await target.edit_text(text, reply_markup=markup)
        return
    rows = today_news_rows(offset)
    buttons = []
    if rows:
        for row in rows:
            buttons.append([colored_button("📰 " + row[1][:55], f"news_item:{row[0]}", "primary")])
        if offset > 0:
            buttons.append([colored_button("⬅️ Новее", f"news_page:{max(0, offset-6)}", "primary")])
        if len(rows) == 6:
            buttons.append([colored_button("Старее ➡️", f"news_page:{offset+6}", "primary")])
        text = "🌐 <b>НОВОСТИ INVESTING.COM · СЕГОДНЯ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for row in rows:
            published = datetime.fromisoformat(row[5]).astimezone(LOCAL_TZ).strftime("%H:%M")
            text += f"\n<b>{published}</b> · {html.escape(row[1][:100])}\n"
    else:
        text = (
            "🌐 <b>НОВОСТИ INVESTING.COM · СЕГОДНЯ</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "В сегодняшнем RSS-потоке пока нет публикаций. Нажмите «Обновить», чтобы получить свежую ленту."
        )
    buttons.append([colored_button("🔄 Обновить", "news_refresh", "primary")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=markup)
    else:
        await target.edit_text(text, reply_markup=markup)


@user_dp.callback_query(F.data.startswith("news_page:"))
async def news_page_callback(callback: CallbackQuery):
    offset = max(0, int(callback.data.split(":", 1)[1]))
    await show_news_page(callback, offset)
    await callback.answer()


@user_dp.callback_query(F.data == "news_refresh")
async def news_refresh_callback(callback: CallbackQuery):
    await fetch_and_store_news()
    await show_news_page(callback, 0)
    await callback.answer(
        localized_user_text(
            callback.from_user.id,
            "Лента обновлена" if NEWS_REPUBLISH_ALLOWED else "Откройте официальный сайт Investing.com",
        )
    )


@user_dp.callback_query(F.data.startswith("news_item:"))
async def news_item_callback(callback: CallbackQuery):
    news_id = int(callback.data.split(":", 1)[1])
    with connect_db() as conn:
        item = conn.execute(
            "SELECT title, description, url, image_url, published_at FROM news WHERE id=?",
            (news_id,),
        ).fetchone()
    if not item:
        await callback.answer(localized_user_text(callback.from_user.id, "Новость не найдена."), show_alert=True)
        return
    title, description, url, image_url, published_at = item
    published = datetime.fromisoformat(published_at).astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M") if published_at else "время не указано источником"
    text = (
        f"📰 <b>{html.escape(title)}</b>\n\n"
        f"{html.escape(description or 'Описание в RSS источником не предоставлено.')}\n\n"
        f"🕒 {published} · Ташкент\n"
        f"Источник: <a href=\"{html.escape(url, quote=True)}\">Investing.com</a>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ Открыть на Investing.com", url=url, style="primary")],
        [colored_button("⬅️ К сегодняшним новостям", "news_back", "primary")],
    ])
    if image_url:
        try:
            await callback.message.answer_photo(image_url, caption=text[:1024], reply_markup=keyboard)
        except TelegramAPIError:
            log.warning("RSS image could not be delivered for news item %s", news_id)
            await callback.message.answer(text, reply_markup=keyboard)
    else:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@user_dp.callback_query(F.data == "news_back")
async def news_back_callback(callback: CallbackQuery):
    await show_news_page(callback, 0)
    await callback.answer()


# =========================================================
# LEGACY ECONOMIC CALENDAR — KEPT, NOT SHOWN IN NEW MENU
# =========================================================

@user_dp.message(Command("calendar"))
@user_dp.message(F.text.in_({"📅 Экономический календарь", "Экономический календарь", "📅 ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ", "🗓 ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ", "ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ", "ECONOMIC CALENDAR"}))
async def calendar_handler(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "📅 <b>ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Календарь макроэкономических событий: время, страна, важность, "
        "фактическое значение и прогноз. Откройте официальный календарь по кнопке ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🗓 Открыть экономический календарь",
                url="https://ru.investing.com/economic-calendar/",
                style="primary",
            )],
        ]),
    )


# =========================================================
# STATISTICS
# =========================================================

def signal_result_kind(details):
    result_text = (details or "").upper()
    # A check is the published result even when the source also leaves its
    # entry timer (⌛) in the post. A missed entry is a loss, never a wait.
    if re.search(
        r"\b(LOSS|LOSE|ПРОИГРЫШ|УБЫТОК|НЕ ЗАШ[ЕЁ]Л|НЕ ВОШ[ЕЁ]Л|NO ENTRY|NOT ENTERED)\b"
        r"|❌|⭕|✖️|➖|🔴",
        result_text,
    ):
        return "loss"
    if re.search(r"\b(WIN|WON|ВЫИГРЫШ|ПРИБЫЛЬ)\b|✅|☑|✔|🗸|✓", result_text):
        return "win"
    return "loss"


def signal_result_marker(details):
    """Use a check for a confirmed entry and a cross for every non-entry result."""
    return "✅" if signal_result_kind(details) == "win" else "❌"


def history_signal_marker(details):
    """Show only a normal check or cross in the user's saved signal history."""
    return signal_result_marker(details)


def is_signal_record(instrument, details):
    """Count only records that identify at least one supported market pair."""
    return bool(extract_pairs(f"{instrument or ''} {details or ''}"))


def ensure_source_signal_record(conn, message_id, text, created_at):
    """Idempotently persist a recognized source post in the signal table."""
    if not is_signal_record("", text):
        return 0
    return conn.execute("""
        INSERT INTO signals
            (instrument, direction, timeframe, details, created_at, created_by, source_message_id)
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM signals WHERE source_message_id=? AND created_by=0
        )
    """, (
        "Публикация", "Источник", "-", (text or "")[:3000], created_at, 0,
        message_id, message_id,
    )).rowcount


def backfill_source_signal_records():
    """Restore missing signal-table rows from the retained source-post history."""
    created = 0
    with connect_db() as conn:
        rows = conn.execute("""
            SELECT p.message_id, p.text, p.created_at
            FROM source_posts AS p
            WHERE NOT EXISTS (
                SELECT 1 FROM signals AS s
                WHERE s.source_message_id=p.message_id AND s.created_by=0
            )
        """).fetchall()
        for message_id, text, created_at in rows:
            created += ensure_source_signal_record(
                conn, message_id, text, created_at or now()
            )
    if created:
        log.info("Restored %s missing source-signal database rows", created)


def compact_signal_text(details):
    """Summarize a source post without copying decorative/check result emoji."""
    raw = html.unescape(re.sub(r"<[^>]+>", " ", details or ""))
    pairs = sorted(extract_pairs(raw))
    timeframe = re.search(r"\b([mhdw])\s*(\d+)\b", raw, re.IGNORECASE)
    direction = re.search(r"\b(вверх|вниз|рост|падение|buy|sell|call|put|up|down)\b", raw, re.IGNORECASE)
    parts = [", ".join(pairs[:3]) if pairs else "Сигнал"]
    if timeframe:
        parts.append(f"{timeframe.group(1).lower()}{timeframe.group(2)}")
    if direction:
        parts.append(direction.group(1).lower())
    return " · ".join(parts)


@user_dp.message(Command("stats"))
@user_dp.message(F.text.in_({"📊 СТАТИСТИКА", "СТАТИСТИКА", "📈 Статистика", "Статистика", "STATISTICS"}))
async def statistics_handler(message: Message):
    if not await check_user(message):
        return

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with connect_db() as conn:
        source_rows = conn.execute(
            "SELECT text FROM source_posts "
            "WHERE created_at >= ? OR COALESCE(updated_at, created_at) >= ?",
            (since, since),
        ).fetchall()
        manual_signals = conn.execute(
            "SELECT instrument, details FROM signals "
            "WHERE (created_by != 0 OR created_by IS NULL) AND created_at >= ?",
            (since,),
        ).fetchall()
    recent_signals = [text for (text,) in source_rows if is_signal_record("", text)]
    recent_signals.extend(
        details for instrument, details in manual_signals
        if is_signal_record(instrument, details)
    )

    wins = 0
    losses = 0
    for (details,) in recent_signals:
        result_kind = signal_result_kind(details)
        if result_kind == "win":
            wins += 1
        elif result_kind == "loss":
            losses += 1
    await message.answer(
        "📊 РЕЗУЛЬТАТЫ ЗА ПОСЛЕДНИЕ 24 ЧАСА\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 Сигналов за сутки: {len(recent_signals)}\n"
        f"✅ WIN: {wins}\n"
        f"❌ LOSS: {losses}"
    )


# =========================================================
# SIGNAL HISTORY
# =========================================================

@user_dp.message(Command("history"))
@user_dp.message(F.text.in_({
    "🕘 ИСТОРИЯ СИГНАЛОВ",
    "ИСТОРИЯ СИГНАЛОВ",
    "🕘 История сигналов",
    "История сигналов",
    "SIGNAL HISTORY",
}))
async def history_handler(message: Message):
    if not await check_user(message):
        return

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with connect_db() as conn:
        channel_rows = conn.execute("""
            SELECT message_id, text, created_at
            FROM source_posts
            WHERE created_at >= ? OR COALESCE(updated_at, created_at) >= ?
            ORDER BY message_id DESC
            LIMIT 50
        """, (since, since)).fetchall()

        manual_rows = conn.execute("""
            SELECT id, instrument, direction, timeframe, details, created_at
            FROM signals
            WHERE (created_by != 0 OR created_by IS NULL) AND created_at >= ?
            ORDER BY id DESC
            LIMIT 50
        """, (since,)).fetchall()

    channel_rows = [row for row in channel_rows if is_signal_record("", row[1])][:50]
    manual_rows = [row for row in manual_rows if is_signal_record(row[1], row[4])]

    if not channel_rows and not manual_rows:
        await message.answer("🕘 История сигналов пока пуста.")
        return

    text = "<b>🕘 ИСТОРИЯ СИГНАЛОВ ЗА 24 ЧАСА</b>\n━━━━━━━━━━━━━━━━━━\n"

    for row in channel_rows:
        body = (row[1] or "").strip()
        text += (
            f"\n<b>{html.escape(compact_signal_text(body))}</b> {history_signal_marker(body)}\n"
            "──────────────\n"
        )

    for row in manual_rows:
        text += (
            f"\n<b>{html.escape(row[1] or '')} · {html.escape(row[3] or '')} · "
            f"{html.escape(row[2] or '')}</b> {history_signal_marker(row[4])}\n"
            "──────────────\n"
        )

    await message.answer(text[:4000])


# =========================================================
# AUTOMATIC BOT
# =========================================================

@user_dp.message(Command("autotrade"))
@user_dp.message(F.text.in_({
    "🤖 АВТОМАТИЧЕСКИЙ БОТ",
    "АВТОМАТИЧЕСКИЙ БОТ",
    "AUTOMATED TRADING BOT",
    "🤖 Автоматический бот",
    "Автоматический бот",
}))
async def autotrade_handler(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "<b>🛡 QUANTUM TRADE AI — 🤖 АВТОМАТИЧЕСКИЙ БОТ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "ВЫБЕРИТЕ ДЕЙСТВИЕ:",
        reply_markup=autotrade_keyboard(),
    )


async def _show_broker_choices(callback: CallbackQuery, back_callback: str):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=broker_choice_keyboard(back_callback)
    )
    await callback.answer()


@user_dp.callback_query(F.data.in_({"choose_broker", "choose_broker_autotrade", "choose_broker_signal"}))
async def broker_choice_handler(callback: CallbackQuery):
    back_callback = (
        "broker_back_signal"
        if callback.data == "choose_broker_signal"
        else "broker_back_autotrade"
    )
    await _show_broker_choices(callback, back_callback)


async def broker_choice_from_signal_handler(callback: CallbackQuery):
    """Compatibility entry point for callers opening broker links from a signal."""
    await _show_broker_choices(callback, "broker_back_signal")


@user_dp.callback_query(F.data == "broker_back_autotrade")
async def broker_back_autotrade_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=autotrade_keyboard())
    await callback.answer()


@user_dp.callback_query(F.data == "broker_back_signal")
async def broker_back_signal_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=signal_action_keyboard())
    await callback.answer()


@user_dp.callback_query(F.data == "support_admin")
async def support_admin_start(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return

    if await state.get_state() == SupportRequest.waiting_text.state:
        await callback.answer(localized_user_text(callback.from_user.id, "Ожидаю ваше сообщение."))
        return

    await state.set_state(SupportRequest.waiting_text)
    await callback.message.answer(
        "Напишите вопрос одним сообщением — я передам его администратору.\n"
        "Для отмены отправьте /cancel."
    )
    await callback.answer()


@user_dp.message(SupportRequest.waiting_text, Command("cancel"))
async def support_admin_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Обращение отменено.")


@user_dp.message(SupportRequest.waiting_text, F.text)
async def support_admin_send(message: Message, state: FSMContext):
    if not message.from_user:
        await state.clear()
        return

    if ADMIN_BOT is None:
        await message.answer("Не удалось передать обращение: бот администратора сейчас недоступен. Попробуйте позже.")
        return

    username = f"@{message.from_user.username}" if message.from_user.username else "не указан"
    admin_text = (
        "📩 <b>Новое обращение в поддержку</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Пользователь: {html.escape(message.from_user.full_name)}\n"
        f"Username: {html.escape(username)}\n"
        f"ID: <code>{message.from_user.id}</code>\n\n"
        f"{html.escape(message.text)}\n\n"
        f"Ответ: <code>/reply {message.from_user.id} текст</code>"
    )
    try:
        await ADMIN_BOT.send_message(OWNER_ID, admin_text)
        await state.clear()
        record_delivery(message.message_id, OWNER_ID, "sent")
        audit(message.from_user.id, "support_request", OWNER_ID)
        await message.answer("Ваше сообщение передано администратору.")
    except TelegramAPIError as error:
        log.exception("Could not deliver support request from user %s", message.from_user.id)
        record_delivery(message.message_id, OWNER_ID, "failed", error)
        record_runtime_error("support_request", error)
        await message.answer("Не удалось передать обращение. Попробуйте отправить его ещё раз позже.")


@user_dp.message(SupportRequest.waiting_text)
async def support_admin_non_text(message: Message):
    await message.answer("Пожалуйста, отправьте обращение текстом. Для отмены — /cancel.")


# =========================================================
# PROFILE
# =========================================================

@user_dp.message(Command("profile"))
@user_dp.message(F.text.in_({"👤 МОЙ ПРОФИЛЬ", "📃 МОЙ ПРОФИЛЬ", "МОЙ ПРОФИЛЬ", "👤 Мой профиль", "Мой профиль", "MY PROFILE"}))
async def profile_handler(message: Message):
    if not await check_user(message):
        return

    user = get_user(message.from_user.id)
    username = "@" + user[1] if user[1] else "не указан"
    status = {
        "active": "🟢 АКТИВЕН",
        "blocked": "📴 НЕАКТИВЕН",
        "suspended": "📴 НЕАКТИВЕН",
    }.get(user[3], "📴 НЕАКТИВЕН")

    profile_emoji = await custom_emoji_markup(message.bot, "👤")
    await message.answer(
        f"<b>{profile_emoji} ЛИЧНЫЙ КАБИНЕТ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: {user[0]}\n"
        f"👤 Имя: {user[2]}\n"
        f"🔗 Username: {username}\n"
        f"❗️ Статус: {status}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛡 QUANTUM TRADE AI"
    )


# =========================================================
# SETTINGS
# =========================================================

@user_dp.message(Command("notifications"))
@user_dp.message(F.text.in_({"🔔 УВЕДОМЛЕНИЯ", "УВЕДОМЛЕНИЯ", "🔔 Уведомления", "Уведомления", "NOTIFICATIONS"}))
async def notifications_handler(message: Message):
    if not await check_user(message):
        return
    user = get_user(message.from_user.id)
    enabled = bool(user[4])
    await message.answer(
        "🔔 УВЕДОМЛЕНИЯ\n━━━━━━━━━━━━━━━━━━\n\n"
        + ("Оповещения о новых сигналах включены." if enabled else "Оповещения о новых сигналах выключены."),
        reply_markup=settings_keyboard(enabled),
    )


@user_dp.message(Command("settings"))
@user_dp.message(F.text.in_({"⚙️ НАСТРОЙКИ", "⚙️ Настройки"}))
async def settings_handler(message: Message):
    # Keep /settings and old keyboard text as compatibility aliases for
    # the single user preference that remains: signal notifications.
    await notifications_handler(message)


@user_dp.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    user = get_user(callback.from_user.id)

    if not user or user[3] != "active":
        await callback.answer(localized_user_text(callback.from_user.id, "Доступ ограничен."), show_alert=True)
        return

    enabled = not bool(user[4])

    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET notifications=?, signals_consent=? WHERE user_id=?",
            (int(enabled), int(enabled), callback.from_user.id),
        )

    user = get_user(callback.from_user.id)
    if "УВЕДОМЛЕНИЯ" in (callback.message.text or "").upper() or "NOTIFICATIONS" in (callback.message.text or "").upper():
        await callback.message.edit_text(
            "🔔 УВЕДОМЛЕНИЯ\n━━━━━━━━━━━━━━━━━━\n\n"
            + ("Оповещения о новых сигналах включены." if enabled else "Оповещения о новых сигналах выключены."),
            reply_markup=settings_keyboard(bool(user[4])),
        )
    else:
        await callback.message.edit_reply_markup(
            reply_markup=settings_keyboard(bool(user[4]))
        )
    await callback.answer(
        localized_user_text(
            callback.from_user.id,
            "Уведомления включены." if enabled else "Уведомления отключены.",
        )
    )


@user_dp.callback_query(F.data.in_(["lang_ru", "lang_en"]))
async def language_handler(callback: CallbackQuery):
    if not get_user(callback.from_user.id):
        await callback.answer(localized_user_text(callback.from_user.id, "Сначала нажмите /start."), show_alert=True)
        return

    language = "ru" if callback.data == "lang_ru" else "en"

    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET language=? WHERE user_id=?",
            (language, callback.from_user.id),
        )

    await callback.answer(
        "Язык интерфейса изменён на русский."
        if language == "ru"
        else "Interface language changed to English."
    )
    current_user = get_user(callback.from_user.id)
    enabled = bool(current_user[4]) if current_user else True
    notice = (
        "🔔 УВЕДОМЛЕНИЯ\n━━━━━━━━━━━━━━━━━━\n\n"
        + ("Оповещения о новых сигналах включены." if enabled else "Оповещения о новых сигналах выключены.")
        if language == "ru"
        else "🔔 NOTIFICATIONS\n━━━━━━━━━━━━━━━━━━\n\n"
        + ("New signal notifications are on." if enabled else "New signal notifications are off.")
    )
    await callback.message.edit_text(
        notice,
        reply_markup=settings_keyboard(enabled),
    )


@user_dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user = get_user(callback.from_user.id)

    if not user:
        await callback.answer(localized_user_text(callback.from_user.id, "Сначала нажмите /start."), show_alert=True)
        return

    username = "@" + user[1] if user[1] else "не указан"
    profile_emoji = await custom_emoji_markup(callback.bot, "👤")

    await callback.message.answer(
        f"<b>{profile_emoji} МОЙ ПРОФИЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: {user[0]}\n"
        f"👤 Имя: {user[2]}\n"
        f"🔗 Username: {username}\n"
        f"❗️ Статус: {'🟢 АКТИВЕН' if user[3] == 'active' else '📴 НЕАКТИВЕН'}\n"
    )
    await callback.answer()


# =========================================================
# SOURCE CHANNEL AUTO-FORWARDING
# =========================================================

async def decorate_signal_copy(bot, user_id, copied_message_id, message, allow_regular_fallback=False):
    """Normalize result stickers in a copied post to one standard Unicode emoji."""
    if message.text:
        limit = 4096
        edit = bot.edit_message_text
        field = "text"
    elif message.caption is not None:
        limit = 1024
        edit = bot.edit_message_caption
        field = "caption"
    else:
        return

    if len(message.text or message.caption or "") > limit - 3:
        return

    original = message.text or message.caption or ""
    status_emojis = re.compile(r"✅|☑️?|✔️?|🗸|✓|⏳|⌛|⭕|❌|✖️?|➖|🔴")
    has_result_marker = bool(status_emojis.search(original))
    is_pair_signal = bool(extract_pairs(original))
    should_mark_result = has_result_marker or is_pair_signal
    if not should_mark_result and not allow_regular_fallback:
        return
    normalized = status_emojis.sub("", original)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized).strip()
    decorated = (
        f"{normalized} {signal_result_marker(original)}".strip()
        if should_mark_result else original
    )
    common = {
        "chat_id": user_id,
        "message_id": copied_message_id,
        "reply_markup": signal_action_keyboard(),
        # Signal copies intentionally keep ordinary Unicode emoji. The global
        # request middleware skips emoji conversion when parse_mode is None.
        "parse_mode": None,
    }
    try:
        if field == "text":
            await edit(**common, text=decorated)
        else:
            await edit(**common, caption=decorated)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            log.warning("Could not normalize emojis in forwarded signal: %s", error)
    except TelegramAPIError:
        log.exception("Could not normalize emojis in forwarded signal %s", copied_message_id)

@user_dp.channel_post(F.chat.id == SOURCE_CHANNEL_ID)
async def signals_pro_channel_handler(message: Message, bot: Bot):
    """
    Copies each new source-channel post to active users
    who have started the user bot and enabled notifications.

    Original post formatting/media are retained by copy_message.
    """
    post_text = message.text or message.caption or ""
    posted_at = now()

    # Record the source post once. On a duplicate Telegram update, retry only
    # deliveries that have not yet been recorded as successful.
    try:
        with connect_db() as conn:
            inserted = conn.execute("""
                INSERT INTO source_posts (message_id, text, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (message.message_id, post_text, posted_at, posted_at)).rowcount
            ensure_source_signal_record(
                conn, message.message_id, post_text, posted_at
            )
            if not inserted:
                log.info("Resuming undelivered recipients for source post %s.", message.message_id)
    except sqlite3.Error:
        log.exception("Could not save source-channel entry.")
        record_runtime_error("source_post_storage", "Could not save source-channel entry")
        return

    with connect_db() as conn:
        recipients = conn.execute("""
            SELECT u.user_id
            FROM users AS u
            WHERE u.status='active' AND u.notifications=1 AND u.signals_consent=1
              AND NOT EXISTS (
                SELECT 1 FROM source_deliveries AS d
                WHERE d.source_message_id=? AND d.user_id=u.user_id
              )
        """, (message.message_id,)).fetchall()

    sent = 0
    failed = 0
    delivery_limit = asyncio.Semaphore(8)

    async def deliver(user_id):
        nonlocal sent, failed
        try:
            async with delivery_limit:
                copied = await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=SOURCE_CHANNEL_ID,
                    message_id=message.message_id,
                    reply_markup=signal_action_keyboard(),
                )
                await decorate_signal_copy(bot, user_id, copied.message_id, message)
            with connect_db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO source_deliveries "
                    "(source_message_id, user_id, copied_message_id) VALUES (?, ?, ?)",
                    (message.message_id, user_id, copied.message_id),
                )
            record_delivery(message.message_id, user_id, "sent")
            sent += 1
        except TelegramAPIError as error:
            failed += 1
            try:
                record_delivery(message.message_id, user_id, "failed", error)
                record_runtime_error("signal_delivery", error)
            except Exception:
                log.exception("Could not record failed delivery")
            log.warning(
                "Could not deliver channel post to user %s: %s",
                user_id,
                error,
            )
        except sqlite3.Error:
            failed += 1
            error = "Could not record source delivery"
            try:
                record_delivery(message.message_id, user_id, "failed", error)
                record_runtime_error("signal_delivery", error)
            except Exception:
                log.exception("Could not record failed delivery")
            log.exception("Could not record source delivery for user %s", user_id)

    await asyncio.gather(*(deliver(user_id) for (user_id,) in recipients))

    log.info(
        "Source entry processed. Delivered=%s Failed=%s",
        sent,
        failed,
    )


@user_dp.edited_channel_post(F.chat.id == SOURCE_CHANNEL_ID)
async def signals_pro_edited_handler(message: Message, bot: Bot):
    source_text = message.text or message.caption or ""
    edited_at = now()
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO source_posts (message_id, text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET "
            "text=excluded.text, updated_at=excluded.updated_at",
            (message.message_id, source_text, edited_at, edited_at),
        )
        ensure_source_signal_record(
            conn, message.message_id, source_text, edited_at
        )
        conn.execute(
            "UPDATE signals SET details=? WHERE source_message_id=?",
            (source_text[:3000], message.message_id),
        )
        deliveries = conn.execute(
            "SELECT user_id, copied_message_id FROM source_deliveries WHERE source_message_id=?",
            (message.message_id,),
        ).fetchall()
    updated = 0
    for user_id, copied_id in deliveries:
        try:
            if message.text or message.caption is not None:
                await decorate_signal_copy(
                    bot, user_id, copied_id, message, allow_regular_fallback=True
                )
            updated += 1
            await asyncio.sleep(0.05)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                record_runtime_error("signal_edit", error)
                log.warning("Could not edit forwarded post for %s: %s", user_id, error)
        except TelegramAPIError:
            log.exception("Could not update forwarded post for user %s", user_id)
    log.info("Source entry edit synchronized for %s users", updated)


# =========================================================
# ADMIN BOT — PANEL
# =========================================================

@admin_dp.message(Command("start", "panel"))
async def admin_start(message: Message):
    if not await check_admin(message):
        return

    await message.answer(
        "🛡 QUANTUM TRADE AI\n"
        "ПАНЕЛЬ УПРАВЛЕНИЯ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Всего пользователей: {get_total_user_count()}\n\n"
        "Выберите нужный раздел:",
        reply_markup=admin_keyboard(),
    )


@admin_dp.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "Укажите его в GitHub Secret OWNER_ID или ADMIN_IDS."
    )


@admin_dp.message(Command("help"))
async def admin_help(message: Message):
    if not await check_admin(message):
        return

    await message.answer(
        "🛡 КОМАНДЫ АДМИНИСТРАТОРА\n\n"
        "/panel — панель управления\n"
        "/stats — статистика\n"
        "/users — пользователи\n"
        "/signal — публикация сигнала\n"
        "/broadcast — рассылка\n"
        "/reply ID текст — ответить на обращение\n"
        "/ban ID — блокировка\n"
        "/unban ID — разблокировка\n"
        "/suspend ID — приостановка\n"
        "/restore ID — восстановление\n"
        "/audit — журнал\n\n"
        "Команды владельца:\n"
        "/addadmin ID\n"
        "/removeadmin ID\n"
        "/adminlist"
    )


# =========================================================
# ADMIN STATISTICS
# =========================================================

@admin_dp.message(Command("stats"))
async def admin_stats(message: Message):
    if not await check_admin(message):
        return

    with connect_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='blocked'"
        ).fetchone()[0]
        signal_rows = conn.execute(
            "SELECT instrument, details FROM signals"
        ).fetchall()
        signals = sum(is_signal_record(instrument, details) for instrument, details in signal_rows)
    await message.answer(
        "📊 СТАТИСТИКА ПЛАТФОРМЫ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"🟢 Активных: {active}\n"
        f"🔴 Заблокированных: {blocked}\n"
        f"📨 Записей сигналов: {signals}"
    )


def get_total_user_count():
    with connect_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# =========================================================
# ADMIN USERS
# =========================================================

@admin_dp.message(Command("users"))
async def admin_users(message: Message):
    if not await check_admin(message):
        return

    with connect_db() as conn:
        rows = conn.execute("""
            SELECT user_id, username, full_name, status
            FROM users
            ORDER BY created_at DESC
            LIMIT 30
        """).fetchall()

    if not rows:
        await message.answer("Пользователей пока нет.")
        return

    text = "👥 ПОЛЬЗОВАТЕЛИ\n━━━━━━━━━━━━━━━━━━\n"
    for row in rows:
        text += (
            f"\nID: {row[0]}\n"
            f"Имя: {row[2]}\n"
            f"Username: @{row[1] or 'нет'}\n"
            f"Статус: {row[3]}\n"
        )

    await message.answer(text[:4000])


# =========================================================
# ADMIN MANUAL SIGNAL PUBLISHING
# =========================================================

@admin_dp.message(Command("signal"))
async def publish_signal(message: Message, bot: Bot):
    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=4)

    if len(parts) < 4:
        await message.answer(
            "Формат команды:\n\n"
            "/signal BTC/USDT BUY M5 комментарий\n\n"
            "Направление: BUY, SELL, CALL или PUT."
        )
        return

    instrument = parts[1].upper()
    direction = parts[2].upper()
    timeframe = parts[3].upper()
    details = parts[4] if len(parts) > 4 else "Без комментария"

    if direction not in ("BUY", "SELL", "CALL", "PUT"):
        await message.answer(
            "Направление должно быть BUY, SELL, CALL или PUT."
        )
        return

    if USER_BOT is None:
        await message.answer("⛔ Пользовательский бот не запущен. Сигнал не отправлен.")
        return
    action_key = f"signal:{message.chat.id}:{message.message_id}"
    with connect_db() as conn:
        inserted = conn.execute(
            "INSERT INTO admin_actions (action_key, created_at) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            (action_key, now()),
        ).rowcount
    if not inserted:
        await message.answer("Эта команда уже обработана; повторная рассылка отменена.")
        return

    with connect_db() as conn:
        cursor = conn.execute("""
            INSERT INTO signals
            (instrument, direction, timeframe, details, created_at, created_by, source_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """ + (" RETURNING id" if DATABASE_URL else ""), (
            instrument,
            direction,
            timeframe,
            details,
            now(),
            message.from_user.id,
            message.message_id,
        ))
        signal_id = cursor.fetchone()[0] if DATABASE_URL else cursor.lastrowid

        recipients = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1 AND signals_consent=1
        """).fetchall()

    text = (
        "🔔 НОВЫЙ СИГНАЛ QUANTUM TRADE AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Инструмент: {html.escape(instrument)}\n"
        f"🎯 Направление: {direction}\n"
        f"⏱ Таймфрейм: {html.escape(timeframe)}\n"
        f"📝 Комментарий: {html.escape(details)}\n"
        f"🆔 Сигнал №{signal_id}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Информационный сигнал. Не является гарантией результата."
    )

    sent = 0
    failed = 0

    for (user_id,) in recipients:
        try:
            await USER_BOT.send_message(user_id, text)
            record_delivery(message.message_id, user_id, "sent")
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError as error:
            failed += 1
            try:
                record_delivery(message.message_id, user_id, "failed", error)
                record_runtime_error("manual_signal_delivery", error)
            except Exception:
                log.exception("Could not record manual signal delivery failure")

    audit(message.from_user.id, "publish_signal", signal_id)

    await message.answer(
        f"✅ Сигнал №{signal_id} опубликован.\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок доставки: {failed}"
    )


# =========================================================
# ADMIN BROADCAST
# =========================================================

@admin_dp.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):
    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат:\n/broadcast Текст сообщения")
        return

    action_key = f"broadcast:{message.chat.id}:{message.message_id}"
    with connect_db() as conn:
        inserted = conn.execute(
            "INSERT INTO admin_actions (action_key, created_at) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            (action_key, now()),
        ).rowcount
    if not inserted:
        await message.answer("Эта рассылка уже обработана; повторная отправка отменена.")
        return

    with connect_db() as conn:
        users = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1 AND signals_consent=1
        """).fetchall()

    delivery_bot = USER_BOT
    if delivery_bot is None:
        await message.answer("⛔ Основной бот ещё не запущен. Рассылка не выполнена.")
        return

    sent = 0
    failed = 0

    for (user_id,) in users:
        try:
            await delivery_bot.send_message(user_id, html.escape(parts[1]))
            record_delivery(message.message_id, user_id, "sent")
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError as error:
            failed += 1
            record_delivery(message.message_id, user_id, "failed", error)
            record_runtime_error("broadcast_delivery", error)

    audit(message.from_user.id, "broadcast")

    await message.answer(
        "📢 РАССЫЛКА ЗАВЕРШЕНА\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}"
    )


@admin_dp.message(Command("reply"))
async def admin_reply(message: Message):
    if not await check_admin(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /reply ID текст ответа")
        return
    if USER_BOT is None:
        await message.answer("Пользовательский бот не подключён.")
        return
    target_id = int(parts[1])
    try:
        await USER_BOT.send_message(
            target_id,
            "📩 <b>Ответ поддержки QUANTUM TRADE AI</b>\n\n" + html.escape(parts[2]),
        )
        record_delivery(message.message_id, target_id, "sent")
        audit(message.from_user.id, "support_reply", target_id)
        await message.answer("✅ Ответ отправлен пользователю.")
    except TelegramAPIError as error:
        log.exception("Could not send admin reply to user %s", target_id)
        record_delivery(message.message_id, target_id, "failed", error)
        record_runtime_error("support_reply", error)
        await message.answer("Не удалось доставить ответ. Пользователь мог заблокировать бота.")


# =========================================================
# ADMIN USER STATUS MANAGEMENT
# =========================================================

async def change_status(message, status):
    if not await check_admin(message):
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажите ID пользователя.")
        return

    user_id = int(parts[1])

    if user_id == OWNER_ID:
        await message.answer("Нельзя изменять статус владельца.")
        return

    set_status(user_id, status)
    audit(message.from_user.id, status, user_id)

    await message.answer(
        f"✅ Статус пользователя {user_id}: {status}"
    )


@admin_dp.message(Command("ban"))
async def ban_user(message: Message):
    await change_status(message, "blocked")


@admin_dp.message(Command("unban"))
async def unban_user(message: Message):
    await change_status(message, "active")


@admin_dp.message(Command("suspend"))
async def suspend_user(message: Message):
    await change_status(message, "suspended")


@admin_dp.message(Command("restore"))
async def restore_user(message: Message):
    await change_status(message, "active")


# =========================================================
# ADMIN AUDIT LOG
# =========================================================

@admin_dp.message(Command("audit"))
async def audit_handler(message: Message):
    if not await check_admin(message):
        return

    with connect_db() as conn:
        rows = conn.execute("""
            SELECT actor_id, action, target_id, created_at
            FROM audit
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    if not rows:
        await message.answer("Журнал действий пока пуст.")
        return

    text = "📋 ЖУРНАЛ ДЕЙСТВИЙ\n━━━━━━━━━━━━━━━━━━\n"
    for row in rows:
        text += (
            f"\nАдминистратор: {row[0]}\n"
            f"Действие: {row[1]}\n"
            f"Пользователь: {row[2]}\n"
            f"Дата: {row[3]}\n"
        )

    await message.answer(text[:4000])


# =========================================================
# OWNER ADMIN MANAGEMENT
# =========================================================

@admin_dp.message(Command("adminlist"))
async def admin_list(message: Message):
    if not await check_owner(message):
        return

    with connect_db() as conn:
        rows = conn.execute(
            "SELECT user_id FROM admins"
        ).fetchall()

    text = f"👑 Владелец: {OWNER_ID}\n\n"
    for row in rows:
        text += f"🛡 Администратор: {row[0]}\n"

    await message.answer(text)


@admin_dp.message(Command("addadmin"))
async def add_admin(message: Message):
    if not await check_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /addadmin ID")
        return

    user_id = int(parts[1])

    with connect_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (user_id,),
        )

    audit(message.from_user.id, "add_admin", user_id)
    await message.answer(f"✅ Администратор {user_id} добавлен.")


@admin_dp.message(Command("removeadmin"))
async def remove_admin(message: Message):
    if not await check_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /removeadmin ID")
        return

    user_id = int(parts[1])

    if user_id in (OWNER_ID, DEFAULT_ADMIN_ID):
        await message.answer(
            "Нельзя удалить владельца или администратора по умолчанию."
        )
        return

    with connect_db() as conn:
        conn.execute(
            "DELETE FROM admins WHERE user_id=?",
            (user_id,),
        )

    audit(message.from_user.id, "remove_admin", user_id)
    await message.answer(f"✅ Права администратора {user_id} сняты.")


# =========================================================
# ADMIN PANEL BUTTON CALLBACKS
# =========================================================

@admin_dp.callback_query(F.data.startswith("admin_"))
async def admin_buttons(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(
            "Нет прав администратора.",
            show_alert=True,
        )
        return

    data = callback.data

    if data == "admin_home":
        await callback.message.edit_text(
            "🛡 <b>QUANTUM TRADE AI · ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
            f"👥 Всего пользователей: {get_total_user_count()}\n\n"
            "Выберите раздел:",
            reply_markup=admin_keyboard(),
        )
        await callback.answer()
        return

    if data == "admin_health":
        await callback.message.edit_text(
            "🩺 МОНИТОРИНГ БОТОВ\n━━━━━━━━━━━━━━━━━━\n\nВыберите раздел:",
            reply_markup=admin_health_keyboard(),
        )
        await callback.answer()
        return

    if data == "admin_health_status":
        try:
            with connect_db() as conn:
                rows = conn.execute(
                    "SELECT component, status, last_seen, details FROM bot_health "
                    "ORDER BY component"
                ).fetchall()
            current_time = datetime.now(timezone.utc)
            labels = {
                "user_bot": "Пользовательский бот",
                "admin_bot": "Админ-бот",
                "database": "База данных",
            }
            lines = ["🟢 СОСТОЯНИЕ СЕРВИСОВ", "━━━━━━━━━━━━━━━━━━"]
            for component, status, last_seen, details in rows:
                try:
                    seen = datetime.fromisoformat(last_seen)
                    if seen.tzinfo is None:
                        seen = seen.replace(tzinfo=timezone.utc)
                    is_fresh = (current_time - seen).total_seconds() <= 90
                except (TypeError, ValueError):
                    is_fresh = False
                online = status == "online" and is_fresh
                lines.append(
                    f"\n{'🟢' if online else '🔴'} {labels.get(component, component)}: "
                    f"{'активен' if online else 'нет свежего сигнала'}"
                )
                lines.append(f"Последняя отметка: {last_seen[:19] if last_seen else '—'} UTC")
                if details:
                    lines.append(html.escape(details))
            if not rows:
                lines.append("\nНет отметок мониторинга. Перезапустите процесс бота.")
        except Exception as error:
            log.exception("Could not load bot health status")
            lines = ["🔴 Не удалось проверить базу данных.", html.escape(str(error)[:300])]
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=admin_health_keyboard()
        )

    elif data == "admin_health_signal":
        with connect_db() as conn:
            signal = conn.execute(
                "SELECT instrument, direction, timeframe, details, created_at, source_message_id "
                "FROM signals ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            delivery = None
            if signal and signal[5] is not None:
                delivery = conn.execute(
                    "SELECT SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), "
                    "MAX(created_at) FROM delivery_events WHERE source_message_id=?",
                    (signal[5],),
                ).fetchone()
        lines = ["📨 ПОСЛЕДНИЙ СИГНАЛ", "━━━━━━━━━━━━━━━━━━"]
        if signal:
            lines.extend([
                f"\nИнструмент: {html.escape(signal[0] or 'Публикация')}",
                f"Направление: {html.escape(signal[1] or '—')}",
                f"Интервал: {html.escape(signal[2] or '—')}",
                f"Время: {html.escape(signal[4] or '—')} UTC",
                f"Текст: {html.escape((signal[3] or '')[:700])}",
            ])
        else:
            lines.append("\nСигналов пока нет.")
        if delivery and delivery[2]:
            lines.append(
                f"\nДоставка сигнала: ✅ {delivery[0] or 0} · "
                f"❌ {delivery[1] or 0} · последняя попытка {delivery[2]} UTC"
            )
        else:
            lines.append("\nПо этому сигналу ещё нет записанных попыток доставки.")
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=admin_health_keyboard()
        )

    elif data == "admin_health_errors":
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT component, description, created_at FROM runtime_errors "
                "ORDER BY id DESC LIMIT 8"
            ).fetchall()
        text = "⚠️ ПОСЛЕДНИЕ ОШИБКИ\n━━━━━━━━━━━━━━━━━━\n"
        for component, description, created_at in rows:
            text += (
                f"\n{created_at[:19]} UTC · {html.escape(component)}\n"
                f"{html.escape(description[:400])}\n──────────────\n"
            )
        if not rows:
            text += "\nСохранённых ошибок пока нет."
        await callback.message.edit_text(
            text[:3900], reply_markup=admin_health_keyboard()
        )

    elif data == "admin_health_delivery":
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with connect_db() as conn:
            sent, failed = conn.execute(
                "SELECT SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) "
                "FROM delivery_events WHERE created_at >= ?", (since,),
            ).fetchone()
            retries = conn.execute(
                "SELECT COALESCE(SUM(attempts - 1), 0) FROM ("
                "SELECT COUNT(*) AS attempts FROM delivery_events "
                "WHERE created_at >= ? GROUP BY source_message_id, user_id "
                "HAVING COUNT(*) > 1)", (since,),
            ).fetchone()[0]
        await callback.message.edit_text(
            "📬 ДОСТАВКА СООБЩЕНИЙ · 24 ЧАСА\n━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Отправлено: {sent or 0}\n"
            f"🔁 Повторных попыток: {retries or 0}\n"
            f"❌ Сбоев: {failed or 0}",
            reply_markup=admin_health_keyboard(),
        )

    if data == "admin_stats":
        with connect_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM users WHERE status='active'"
            ).fetchone()[0]
            blocked = conn.execute(
                "SELECT COUNT(*) FROM users WHERE status='blocked'"
            ).fetchone()[0]
            signal_rows = conn.execute(
                "SELECT instrument, details FROM signals"
            ).fetchall()
            signals = sum(is_signal_record(instrument, details) for instrument, details in signal_rows)
        await callback.message.edit_text(
            "📊 СТАТИСТИКА QUANTUM TRADE AI\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Пользователей: {total}\n"
            f"🟢 Активных: {active}\n"
            f"🔴 Заблокированных: {blocked}\n"
            f"📨 Записей сигналов: {signals}",
            reply_markup=admin_back_keyboard(),
        )

    elif data == "admin_users":
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT user_id, username, full_name, status
                FROM users ORDER BY created_at DESC LIMIT 20
            """).fetchall()
        text = "👥 <b>ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for user_id, username, full_name, status in rows:
            text += f"\n<code>{user_id}</code> · {html.escape(full_name or '')} · @{html.escape(username or 'нет')} · {status}"
        text += "\n\nИзменение статуса: /ban ID · /suspend ID · /restore ID"
        await callback.message.edit_text(text[:4000], reply_markup=admin_back_keyboard())

    elif data == "admin_signals":
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT id, instrument, direction, timeframe, created_at
                FROM signals
                ORDER BY id DESC
                LIMIT 10
            """).fetchall()

        if not rows:
            await callback.message.edit_text("Сигналов пока нет.", reply_markup=admin_back_keyboard())
        else:
            text = "📨 ПОСЛЕДНИЕ СИГНАЛЫ\n━━━━━━━━━━━━━━━━━━\n"
            for row in rows:
                is_source_post = row[2] in ("CHANNEL POST", "Источник")
                instrument = "Публикация" if is_source_post else row[1]
                direction = "Источник" if is_source_post else row[2]
                text += (
                    f"\n#{row[0]} {instrument} {direction} {row[3]}\n"
                    f"{row[4]}\n"
                )
            text += (
                "\nДля ручной публикации:\n"
                "/signal BTC/USDT BUY M5 комментарий"
            )
            await callback.message.edit_text(text[:4000], reply_markup=admin_back_keyboard())

    elif data == "admin_broadcast":
        await callback.message.edit_text(
            "📢 РАССЫЛКА\n\n"
            "Формат:\n/broadcast Текст сообщения",
            reply_markup=admin_back_keyboard(),
        )

    elif data == "admin_blocks":
        await callback.message.edit_text(
            "🚫 УПРАВЛЕНИЕ ДОСТУПОМ\n\n"
            "🔴 /ban ID — блокировка\n"
            "🟢 /unban ID — снять блокировку\n"
            "🔵 /suspend ID — приостановка\n"
            "🟢 /restore ID — восстановление",
            reply_markup=admin_back_keyboard(),
        )

    elif data == "admin_manage":
        if callback.from_user.id != OWNER_ID:
            await callback.answer(
                "Управлять администраторами может только владелец.",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            "🛡 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ\n\n"
            "/adminlist — список\n"
            "/addadmin ID — добавить\n"
            "/removeadmin ID — удалить",
            reply_markup=admin_back_keyboard(),
        )

    elif data == "admin_audit":
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT actor_id, action, target_id, created_at
                FROM audit ORDER BY id DESC LIMIT 15
            """).fetchall()
        text = "📋 <b>ЖУРНАЛ ДЕЙСТВИЙ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for actor, action, target, created in rows:
            text += f"\n{created[:19]} · {actor} · {html.escape(action)} · {target or '—'}"
        if not rows:
            text += "\nЖурнал пока пуст."
        await callback.message.edit_text(text[:4000], reply_markup=admin_back_keyboard())

    elif data == "admin_settings":
        await callback.message.edit_text(
            "⚙️ НАСТРОЙКИ БОТА\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📡 Автоматическая обработка публикаций включена.",
            reply_markup=admin_back_keyboard(),
        )

    await callback.answer()


# =========================================================
# RUN BOTH BOTS
# =========================================================

async def main():
    global USER_BOT, ADMIN_BOT
    init_db()
    backfill_source_signal_records()

    if not TOKEN_USER:
        raise RuntimeError("Не задан GitHub Secret TOKEN_USER")

    if not TOKEN_ADMIN:
        raise RuntimeError("Не задан GitHub Secret TOKEN_ADMIN")

    user_bot = Bot(token=TOKEN_USER, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    admin_bot = Bot(token=TOKEN_ADMIN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    USER_BOT = user_bot
    ADMIN_BOT = admin_bot
    await setup_custom_emojis(user_bot)
    await setup_custom_emojis(admin_bot)

    try:
        user_info, admin_info = await asyncio.gather(
            user_bot.get_me(),
            admin_bot.get_me(),
        )

        user_commands = [
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="signals", description="Сигналы для бинарных опционов"),
            BotCommand(command="calendar", description="Экономический календарь"),
            BotCommand(command="stats", description="Результаты за последние 24 часа"),
            BotCommand(command="history", description="История сигналов за сутки"),
            BotCommand(command="autotrade", description="Подключение автоторговли"),
            BotCommand(command="notifications", description="Настройки уведомлений"),
            BotCommand(command="profile", description="Мой профиль"),
        ]
        admin_commands = [
            BotCommand(command="start", description="Открыть панель администратора"),
            BotCommand(command="panel", description="Открыть панель администратора"),
            BotCommand(command="help", description="Список команд администратора"),
            BotCommand(command="myid", description="Показать Telegram ID"),
            BotCommand(command="stats", description="Статистика пользователей и сигналов"),
            BotCommand(command="users", description="Последние пользователи"),
            BotCommand(command="signal", description="Опубликовать сигнал"),
            BotCommand(command="broadcast", description="Отправить рассылку"),
            BotCommand(command="reply", description="Ответить пользователю по ID"),
            BotCommand(command="ban", description="Заблокировать пользователя"),
            BotCommand(command="unban", description="Снять блокировку"),
            BotCommand(command="suspend", description="Приостановить доступ"),
            BotCommand(command="restore", description="Восстановить доступ"),
            BotCommand(command="audit", description="Журнал действий"),
            BotCommand(command="adminlist", description="Список администраторов"),
            BotCommand(command="addadmin", description="Добавить администратора"),
            BotCommand(command="removeadmin", description="Удалить администратора"),
        ]
        await user_bot.set_my_commands(user_commands)
        await admin_bot.set_my_commands(admin_commands)

        log.info("Пользовательский бот: @%s", user_info.username)
        log.info("Административный бот: @%s", admin_info.username)
        log.info("Источник канала: %s", SOURCE_CHANNEL_ID)
        log.info("Investing.com RSS: %s", NEWS_RSS_URL)

        # Verify that the USER bot is an administrator of the source channel.
        try:
            member = await user_bot.get_chat_member(
                SOURCE_CHANNEL_ID,
                user_info.id,
            )
            log.info("Статус пользовательского бота в канале: %s", member.status)
        except TelegramAPIError:
            log.exception(
                "Не удалось проверить доступ к каналу публикаций. "
                "Проверьте ID канала и права пользовательского бота."
            )

        async def news_refresh_worker():
            while True:
                await fetch_and_store_news()
                await asyncio.sleep(NEWS_POLL_SECONDS)

        for component, details in (
            ("user_bot", f"@{user_info.username}"),
            ("admin_bot", f"@{admin_info.username}"),
            ("database", "PostgreSQL" if DATABASE_URL else "SQLite"),
        ):
            set_health(component, "online", details)

        async def health_refresh_worker():
            while True:
                await asyncio.sleep(30)
                try:
                    set_health("user_bot", "online", f"@{user_info.username}")
                    set_health("admin_bot", "online", f"@{admin_info.username}")
                    set_health("database", "online", "Соединение проверено heartbeat-записью")
                except Exception:
                    log.exception("Bot health heartbeat failed")

        pollers = [
            user_dp.start_polling(
                user_bot,
                allowed_updates=user_dp.resolve_used_update_types(),
                close_bot_session=False,
            ),
            admin_dp.start_polling(
                admin_bot,
                allowed_updates=admin_dp.resolve_used_update_types(),
                close_bot_session=False,
            ),
            health_refresh_worker(),
        ]
        if NEWS_REPUBLISH_ALLOWED:
            pollers.append(news_refresh_worker())
        await asyncio.gather(*pollers)
    except TelegramConflictError:
        log.exception("Polling conflict: another instance is already using one of these bot tokens.")
        record_runtime_error("polling_conflict", "Another instance is already using one of these bot tokens")
        raise
    except Exception as error:
        log.exception("Fatal bot runtime error")
        record_runtime_error("bot_runtime", error)
        raise

    finally:
        try:
            for component in ("user_bot", "admin_bot", "database"):
                set_health(component, "offline", "Процесс остановлен")
        except Exception:
            log.exception("Could not mark bot services offline")
        await user_bot.session.close()
        await admin_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
