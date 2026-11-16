# QUANTUM TRADE AI V2

The project runs two separate Telegram bots. The user bot provides opt-in signal delivery and the news/pair menus. The admin bot provides moderation, support replies, signal publishing and broadcasts. Broadcasts are sent only by the user bot to active users who accepted signal delivery and left notifications enabled.

## Configuration

Required GitHub Actions secrets: `TOKEN_USER` and `TOKEN_ADMIN`. Admin IDs are initialized from `OWNER_ID` (default `770710937`), `DEFAULT_ADMIN_ID` (default `5232049751`) and optional comma-separated `ADMIN_IDS`. `/myid` displays the calling Telegram ID without exposing bot tokens. Configure the owner secret if the built-in ID is not the real owner.

Optional environment variables: `DATABASE_URL`, `DB_PATH`, `INTRO_GIF_PATH`, `INTRO_GIF_FILE_ID`, `CUSTOM_EMOJI_PACK_NAME`, `NEWS_RSS_URL`, `NEWS_POLL_SECONDS`, and `NEWS_REPUBLISH_ALLOWED`. The bot defaults to the `AR_PREMIUM` custom emoji pack. If it loads successfully, outgoing messages and supported button icons use the pack wherever a matching emoji exists; otherwise the regular emoji are retained. Telegram requires Premium for custom emoji entities in messages. Set `DATABASE_URL` to a PostgreSQL connection string to store users, source-post deduplication, signal history, and news in a managed SQL database. If it is empty, the bot uses local SQLite at `DB_PATH`. The news reader is wired to the official Investing.com RSS endpoint (`https://www.investing.com/rss/news.rss`) but ingestion and in-bot display are **off by default**. Investing.com's general site terms restrict redistribution of its content; only set `NEWS_REPUBLISH_ALLOWED=true` after you have confirmed that your use is permitted. When enabled, the bot polls the RSS feed, stores deduplicated items in the configured database and shows items published since midnight in Tashkent. It uses RSS fields only; it does not scrape article pages or invent missing images/descriptions. Without permission, the bot offers direct links to Investing.com and its RSS terms instead of copying headlines or images. The broker-support button opens `https://t.me/copy_broker_BO_bot` with the prepared draft `Здравствуйте! 🤝 Хочу подключить автоторговлю!` for the user to send; the autotrade screen contains only registration and support actions. Registration uses the supplied link `https://clck.ru/3X2xAM`.

## What is implemented

- `/start` greets first-time users with an animated custom emoji from the selected pack, then asks for signal consent. The bundled intro GIF is used as a captioned fallback if the pack cannot be loaded. Existing consent is retained on later `/start` calls.
- The intro animation is included at `assets/quantum_trade_ai_intro.gif`; the original project GIF is retained too.
- New signal-channel posts are copied to opted-in users with an animated emoji prefix and action buttons. Per-user delivery IDs are stored in SQLite; edited text/captions update the same copies where Telegram permits. Unsupported edits are logged without resending duplicates.
- Binary options menu shows the requested forex and BTC/USD pairs with actual stored signal counts; it clearly indicates when it is waiting for a source-channel signal.
- News refreshes from the official RSS feed on startup, every configured interval and when the user opens/refreshes the news menu. Articles have a detail view and original-source link. Image-free RSS entries remain image-free.
- Admin commands: `/start`, `/panel`, `/myid`, `/stats`, `/users`, `/signal PAIR BUY M5 note`, `/broadcast text`, `/reply USER_ID text`, `/audit`, `/addadmin ID`, `/removeadmin ID`, `/adminlist`, `/ban ID`, `/unban ID`, `/suspend ID`, `/restore ID`.
- Admin button styling uses aiogram's `style` support; clients that do not render Bot API button styles use their default appearance.
- The automatic trading section links to broker registration and support, and includes a separate text-to-admin support form. It does not claim to place trades or provide results it cannot verify.

## Local run (PowerShell)

```powershell
python -m pip install -r requirements.txt
$env:TOKEN_USER = "..."
$env:TOKEN_ADMIN = "..."
$env:OWNER_ID = "your-telegram-id"
python bot.py
```

The user bot must be a member of SIGNALS PRO (`-1003979525371`) and receive channel-post updates. Do not run two polling copies with the same tokens.

## GitHub Actions and persistent hosting

The workflow is manually dispatched and serializes runs so the same tokens are not polled by concurrent workflow instances. GitHub-hosted runners are time-limited; their local SQLite file is ephemeral and disappears between runs. Configure the GitHub Actions secret `DATABASE_URL` to use a managed PostgreSQL database for persistent history. Before switching databases, export the existing `quantum.db` and import it with `python migrate_sqlite_to_postgres.py quantum.db` while `DATABASE_URL` points to PostgreSQL. A database alone does not keep the bot process online: the workflow has a 350-minute limit. For reliable 24/7 polling, run exactly one bot process on an always-on worker or VPS and set the same `DATABASE_URL` there. Free app plans may sleep or have usage limits and should not be presented as guaranteed 24/7 hosting; check the provider's current plan limits before moving real user data.

## Deploy on your VPS with Docker Compose

The `compose.yaml` runs PostgreSQL and the bot with restart policies and a persistent Docker volume. The database port is not exposed publicly. On a Linux VPS with Docker Compose installed:

```sh
git clone https://github.com/r3191261-svg/QUANTUM-TRADE-AI-V2.git
cd QUANTUM-TRADE-AI-V2
cp .env.example .env
openssl rand -hex 32
```

Put the generated hex string into `POSTGRES_PASSWORD` in `.env`, fill in both bot tokens and the real owner ID, then start once:

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
```

To migrate an existing SQLite file before starting the bot, copy `quantum.db` securely to the VPS, then run:

```sh
docker compose run --rm \
  -v /absolute/path/quantum.db:/migration/quantum.db:ro \
  bot python migrate_sqlite_to_postgres.py /migration/quantum.db
```

Migrate only once. Stop the old GitHub Actions poller before starting the VPS bot so the same Telegram tokens are never polled by two instances. Keep `.env` only on the VPS, and make regular PostgreSQL backups.

Signals and news are informational only and are not financial advice. Real automatic execution requires a documented Intrade Bar API, credentials, and explicit integration work; none are present in this repository.
