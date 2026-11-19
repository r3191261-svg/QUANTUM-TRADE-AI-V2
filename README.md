# QUANTUM TRADE AI V2

The project runs two separate Telegram bots. The user bot provides opt-in signal delivery and the news/pair menus. The admin bot provides moderation, support replies, signal publishing and broadcasts. Broadcasts are sent only by the user bot to active users who accepted signal delivery and left notifications enabled.

## Configuration

Required GitHub Actions secrets: `TOKEN_USER` and `TOKEN_ADMIN`. Admin IDs are initialized from `OWNER_ID` (default `770710937`), `DEFAULT_ADMIN_ID` (default `5232049751`) and optional comma-separated `ADMIN_IDS`. `/myid` displays the calling Telegram ID without exposing bot tokens. Configure the owner secret if the built-in ID is not the real owner.

Optional environment variables: `DATABASE_URL`, `DB_PATH`, `INTRO_GIF_PATH`, `INTRO_GIF_FILE_ID`, `CUSTOM_EMOJI_PACK_NAMES`, `NEWS_RSS_URL`, `NEWS_POLL_SECONDS`, `NEWS_REPUBLISH_ALLOWED`, and `MINI_APP_URL`. The bot loads custom emoji from the selected packs. Set `DATABASE_URL` to a PostgreSQL connection string to store users, source-post deduplication, signal history, and news. If it is empty, the bot uses local SQLite. RSS ingestion and news display are off by default until redistribution is permitted. The Mini App URL must be public HTTPS; after deploying the web service, set `MINI_APP_URL` as a GitHub Actions repository variable. The bot then displays an app button in the keyboard and Telegram menu.

## What is implemented

- `/start` greets first-time users with an animated custom emoji from the selected pack, then asks for signal consent. The bundled intro GIF is used as a captioned fallback if the pack cannot be loaded. Existing consent is retained on later `/start` calls.
- The intro animation is included at `assets/quantum_trade_ai_intro.gif`; the original project GIF is retained too.
- New signal-channel posts are copied to opted-in users with an animated emoji prefix and action buttons. Per-user delivery IDs are stored in SQLite; edited text/captions update the same copies where Telegram permits. Unsupported edits are logged without resending duplicates.
- Binary options menu has “Все валютные пары” and “За последние 10 минут” reports. Counts use real saved SIGNALS PRO publications and do not guess unrecognized pairs.
- News refreshes from the official RSS feed on startup, every configured interval and when the user opens/refreshes the news menu. Articles have a detail view and original-source link. Image-free RSS entries remain image-free.
- Admin commands: `/start`, `/panel`, `/myid`, `/stats`, `/users`, `/signal PAIR BUY M5 note`, `/broadcast text`, `/reply USER_ID text`, `/audit`, `/addadmin ID`, `/removeadmin ID`, `/adminlist`, `/ban ID`, `/unban ID`, `/suspend ID`, `/restore ID`.
- Admin button styling uses aiogram's `style` support; clients that do not render Bot API button styles use their default appearance.
- The automatic trading section links to broker registration and support, and includes a separate text-to-admin support form. It does not claim to place trades or provide results it cannot verify.
- A separate mobile-first Telegram Mini App lives in `mini_app/`. Its `aiohttp` backend verifies Telegram `initData` HMAC and reads the shared PostgreSQL user, delivered-signal, history, and permitted-news records. The chart screen embeds TradingView. It does not invent prices, results, news, images, or AI forecasts; a separate AI/indicator service is not configured.

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

The workflow runs on push, by manual dispatch, and on a five-hour schedule; concurrency prevents duplicate pollers. Each GitHub-hosted run has a 350-minute limit. A scheduled restart is best-effort and can be delayed. `DATABASE_URL` points the bot to managed PostgreSQL because runner-local files disappear between runs.

## Telegram Mini App cloud service

The Mini App backend is a separate Render web service so Telegram can reach it over HTTPS. The repository includes `render.yaml`; in Render choose **New → Blueprint** and connect this public repository. During setup, provide `TOKEN_USER` and the same managed-Postgres `DATABASE_URL` used by the bot. Do not commit either value. After the service deploys, copy its `https://…onrender.com` URL into the GitHub repository variable `MINI_APP_URL`; the next bot run will add the Mini App button.

Render's free web service is suitable for preview, not uninterrupted production: it can sleep after inactivity and cold-start on the next request. The Telegram polling bot remains a separate cloud process in GitHub Actions. Both services use the same PostgreSQL database. News republication stays disabled until rights are confirmed.

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
