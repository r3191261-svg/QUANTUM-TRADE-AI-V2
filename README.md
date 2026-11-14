# QUANTUM TRADE AI V2

The project runs two separate Telegram bots. The user bot provides opt-in signal delivery and the news/pair menus. The admin bot provides moderation, support replies, signal publishing and broadcasts. Broadcasts are sent only by the user bot to active users who accepted signal delivery and left notifications enabled.

## Configuration

Required GitHub Actions secrets: `TOKEN_USER` and `TOKEN_ADMIN`. Admin IDs are initialized from `OWNER_ID` (default `770710937`), `DEFAULT_ADMIN_ID` (default `5232049751`) and optional comma-separated `ADMIN_IDS`. `/myid` displays the calling Telegram ID without exposing bot tokens. Configure the owner secret if the built-in ID is not the real owner.

Optional environment variables: `DB_PATH`, `INTRO_GIF_PATH`, `INTRO_GIF_FILE_ID`, `NEWS_RSS_URL`, `NEWS_POLL_SECONDS`, `NEWS_REPUBLISH_ALLOWED`, and `SUPPORT_URL`. The news reader is wired to the official Investing.com RSS endpoint (`https://www.investing.com/rss/news.rss`) but ingestion and in-bot display are **off by default**. Investing.com's general site terms restrict redistribution of its content; only set `NEWS_REPUBLISH_ALLOWED=true` after you have confirmed that your use is permitted. When enabled, the bot polls the RSS feed, stores deduplicated items in SQLite and shows items published since midnight in Tashkent. It uses RSS fields only; it does not scrape article pages or invent missing images/descriptions. Without permission, the bot offers direct links to Investing.com and its RSS terms instead of copying headlines or images. `SUPPORT_URL` can be set to a public Telegram URL for the project administrator; if unset, the bot collects a message and forwards it to the configured owner ID.

## What is implemented

- `/start` sends the intro animation without a caption, then asks first-time users for signal consent. Existing consent is retained on later `/start` calls.
- The intro animation is included at `assets/quantum_trade_ai_intro.gif`; the original project GIF is retained too.
- New SIGNALS PRO channel posts are copied to opted-in users. Per-user delivery IDs are stored in SQLite; edited text/captions update the same copies where Telegram permits. Unsupported edits are logged without resending duplicates.
- Binary options menu lists only pairs found in stored source posts and calculates actual post/pair counts from the last ten minutes.
- News refreshes from the official RSS feed on startup, every configured interval and when the user opens/refreshes the news menu. Articles have a detail view and original-source link. Image-free RSS entries remain image-free.
- Admin commands: `/start`, `/panel`, `/myid`, `/stats`, `/users`, `/signal PAIR BUY M5 note`, `/broadcast text`, `/reply USER_ID text`, `/audit`, `/addadmin ID`, `/removeadmin ID`, `/adminlist`, `/ban ID`, `/unban ID`, `/suspend ID`, `/restore ID`.
- Admin button styling uses aiogram's `style` support; clients that do not render Bot API button styles use their default appearance.
- The automatic trading section has registration and QUANTUM support buttons, contains no partner ID, and states that no Intrade Bar execution API is configured. The bot does not claim to place trades or provide results it cannot verify.

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

The workflow is manually dispatched and serializes runs so the same tokens are not polled by concurrent workflow instances. GitHub-hosted runners are time-limited; their local SQLite file is ephemeral and disappears between runs. This means they are suitable for a temporary run, not reliable 24/7 operation or durable user/news/delivery history. For continuous operation, run one instance on a VPS with a persistent disk and back up `quantum.db`, or move the data to a managed database before scaling out.

Signals and news are informational only and are not financial advice. Real automatic execution requires a documented Intrade Bar API, credentials, and explicit integration work; none are present in this repository.
