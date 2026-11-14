# QUANTUM TRADE AI

Two Telegram bots: the user bot delivers opt-in SIGNALS PRO posts and user features; the admin bot provides private management commands. Only the user bot sends subscriber broadcasts.

## Configuration

Required environment variables: `TOKEN_USER`, `TOKEN_ADMIN`. Configure `OWNER_ID` as the owner Telegram numeric ID. Optional admin IDs: `DEFAULT_ADMIN_ID` and comma-separated `ADMIN_IDS`. If the admin bot says access is denied, send `/myid` there and add the returned ID as the `OWNER_ID` or `ADMIN_IDS` GitHub Actions secret.

Optional variables: `DB_PATH`, `INTRO_GIF_PATH`, `INTRO_GIF_FILE_ID`. The bundled intro animation is used by default. Database changes are additive; keep `quantum.db` on persistent storage to preserve consent, history, and duplicate-delivery records.

## Local run (PowerShell)

```powershell
python -m pip install -r requirements.txt
$env:TOKEN_USER = "..."
$env:TOKEN_ADMIN = "..."
$env:OWNER_ID = "your-telegram-id"
python bot.py
```

Admin commands include `/start`, `/myid`, `/stats`, `/users`, `/signal PAIR BUY M5 note`, `/broadcast text`, `/reply USER_ID text`, `/audit`, `/addadmin ID`, `/removeadmin ID`, `/adminlist`, `/ban ID`, `/unban ID`, `/suspend ID`, and `/restore ID`.

## GitHub Actions and hosting

The workflow uses manual `workflow_dispatch` only, so a code push will not unexpectedly start a live bot instance. Add `TOKEN_USER`, `TOKEN_ADMIN`, and `OWNER_ID` to repository Actions secrets, then manually start the workflow. Its hosted runner is time-limited and its local SQLite file is temporary; use a VPS and persistent storage for reliable 24/7 polling. Run exactly one polling instance per bot token.

The user bot must be able to read SIGNALS PRO (`-1003979525371`). Users receive signals only after starting the user bot and opting in.
