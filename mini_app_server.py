"""HTTPS-ready Telegram Mini App API, served beside the static Mini App."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl

from aiohttp import web

import bot as quantum_bot


log = logging.getLogger("quantum.miniapp")
WEB_ROOT = Path(__file__).resolve().parent / "mini_app"
MAX_INIT_DATA_AGE = 24 * 60 * 60
MAX_FUTURE_SKEW = 5 * 60


class MiniAppAuthError(Exception):
    pass


def validate_telegram_init_data(raw_init_data, bot_token=None):
    """Verify Telegram WebApp initData using the Bot API HMAC procedure."""
    token = bot_token or quantum_bot.TOKEN_USER
    if not token:
        raise MiniAppAuthError("Mini App authentication is not configured")
    if not raw_init_data or len(raw_init_data) > 8192:
        raise MiniAppAuthError("Missing or oversized Telegram initData")

    try:
        pairs = parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise MiniAppAuthError("Telegram initData is malformed") from error
    values = dict(pairs)
    if len(values) != len(pairs):
        raise MiniAppAuthError("Telegram initData contains duplicate fields")
    received_hash = values.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", received_hash):
        raise MiniAppAuthError("Invalid Telegram initData hash")

    auth_date_text = values.get("auth_date", "")
    try:
        auth_date = int(auth_date_text)
    except (TypeError, ValueError) as error:
        raise MiniAppAuthError("Invalid Telegram auth date") from error
    now_seconds = int(time.time())
    if auth_date > now_seconds + MAX_FUTURE_SKEW or now_seconds - auth_date > MAX_INIT_DATA_AGE:
        raise MiniAppAuthError("Telegram initData has expired")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise MiniAppAuthError("Telegram initData signature did not match")

    try:
        user = json.loads(values["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MiniAppAuthError("Telegram user data is invalid") from error
    if user_id <= 0:
        raise MiniAppAuthError("Telegram user ID is invalid")
    return user


def _init_data_from_request(request):
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("tma "):
        return authorization[4:]
    return request.headers.get("X-Telegram-Init-Data", "")


@web.middleware
async def api_auth_middleware(request, handler):
    if request.path == "/healthz" or request.path == "/" or not request.path.startswith("/api/"):
        return await handler(request)
    try:
        request["telegram_user"] = validate_telegram_init_data(_init_data_from_request(request))
    except MiniAppAuthError as error:
        return web.json_response({"error": str(error)}, status=401)

    user_id = int(request["telegram_user"]["id"])
    user = await asyncio.to_thread(quantum_bot.get_user, user_id)
    if user and user[3] != "active":
        return web.json_response({"error": "Account access is disabled"}, status=403)
    if not user:
        telegram_user = request["telegram_user"]
        full_name = " ".join(filter(None, [telegram_user.get("first_name"), telegram_user.get("last_name")]))
        await asyncio.to_thread(
            quantum_bot.register_user,
            SimpleNamespace(id=user_id, username=telegram_user.get("username"), full_name=full_name),
        )
    return await handler(request)


def _signal_payload(message_id, body, created_at, updated_at=None):
    body = body or ""
    pairs = sorted(quantum_bot.extract_pairs(body))
    timeframe = re.search(r"\b([mhdw])\s*(\d+)\b", body, re.IGNORECASE)
    direction = re.search(
        r"\b(вверх|вниз|рост|падение|buy|sell|call|put|up|down)\b",
        body,
        re.IGNORECASE,
    )
    kind = quantum_bot.signal_result_kind(body)
    return {
        "id": str(message_id),
        "pair": pairs[0] if pairs else "",
        "pairs": pairs,
        "timeframe": f"{timeframe.group(1).lower()}{timeframe.group(2)}" if timeframe else "",
        "direction": direction.group(1).lower() if direction else "",
        "status": kind,
        "text": body[:3000],
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _is_tashkent_today(value):
    if not value:
        return False
    try:
        timestamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=quantum_bot.LOCAL_TZ)
    return timestamp.astimezone(quantum_bot.LOCAL_TZ).date() == datetime.now(quantum_bot.LOCAL_TZ).date()


def load_app_profile(user_id):
    with quantum_bot.connect_db() as conn:
        row = conn.execute(
            "SELECT user_id, username, full_name, status, notifications, language, created_at "
            "FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        signals = conn.execute(
            "SELECT p.message_id, p.text, p.created_at, p.updated_at "
            "FROM source_posts AS p JOIN source_deliveries AS d "
            "ON d.source_message_id=p.message_id WHERE d.user_id=? "
            "ORDER BY p.created_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    history = [_signal_payload(*signal) for signal in signals]
    recent = [item for item in history if _is_tashkent_today(item["created_at"])]
    wins = sum(item["status"] == "win" for item in recent)
    losses = sum(item["status"] == "loss" for item in recent)
    return {
        "id": str(row[0]),
        "username": row[1] or "",
        "name": row[2] or "",
        "status": row[3],
        "notifications": bool(row[4]),
        "language": row[5] or "ru",
        "created_at": row[6],
        "signals_today": len(recent),
        "wins_today": wins,
        "losses_today": losses,
        "signals": history,
    }


async def health(request):
    return web.json_response({"status": "ok", "service": "quantum-mini-app"})


async def app_index(request):
    return web.FileResponse(WEB_ROOT / "index.html")


async def app_static(request):
    name = request.match_info["name"]
    if name not in {"app.js", "style.css", "logo.svg"}:
        raise web.HTTPNotFound()
    return web.FileResponse(WEB_ROOT / name)


async def api_me(request):
    user_id = int(request["telegram_user"]["id"])
    profile = await asyncio.to_thread(load_app_profile, user_id)
    if not profile:
        return web.json_response({"error": "User not found"}, status=404)
    return web.json_response(profile)


async def api_signals(request):
    user_id = int(request["telegram_user"]["id"])
    profile = await asyncio.to_thread(load_app_profile, user_id)
    status = request.query.get("status", "all")
    signals = profile["signals"] if profile else []
    if status == "open":
        signals = [item for item in signals if item["status"] == "pending"]
    elif status == "history":
        signals = [item for item in signals if item["status"] != "pending"]
    elif status != "all":
        return web.json_response({"error": "Unsupported status filter"}, status=400)
    return web.json_response({"signals": signals})


async def api_news(request):
    if not quantum_bot.NEWS_REPUBLISH_ALLOWED:
        return web.json_response({"enabled": False, "news": []})

    def read_news():
        with quantum_bot.connect_db() as conn:
            return conn.execute(
                "SELECT source_key, title, description, url, image_url, published_at "
                "FROM news ORDER BY published_at DESC LIMIT 30"
            ).fetchall()

    rows = await asyncio.to_thread(read_news)
    return web.json_response({
        "enabled": True,
        "news": [
            {"id": row[0], "title": row[1], "description": row[2] or "", "url": row[3],
             "image": row[4] or "", "published_at": row[5]}
            for row in rows
        ],
    })


async def api_notifications(request):
    user_id = int(request["telegram_user"]["id"])
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Expected JSON body"}, status=400)
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    if not isinstance(enabled, bool):
        return web.json_response({"error": "enabled must be true or false"}, status=400)
    await asyncio.to_thread(quantum_bot.set_notification_preferences, user_id, enabled)
    return web.json_response({"notifications": enabled})


async def api_market_config(request):
    return web.json_response({
        "registration_url": "https://go.intrade.bar/n4FmpAFBYfvE",
        "support_url": quantum_bot.SUPPORT_URL,
        "news_enabled": quantum_bot.NEWS_REPUBLISH_ALLOWED,
        "data_notice": "Quotes and charts are supplied by TradingView. Signal results mirror saved source posts.",
    })


def create_app():
    app = web.Application(middlewares=[api_auth_middleware], client_max_size=16 * 1024)
    app.router.add_get("/healthz", health)
    app.router.add_get("/", app_index)
    app.router.add_get("/{name}", app_static)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/signals", api_signals)
    app.router.add_get("/api/news", api_news)
    app.router.add_post("/api/notifications", api_notifications)
    app.router.add_get("/api/config", api_market_config)
    return app


async def main():
    if not quantum_bot.TOKEN_USER:
        raise RuntimeError("TOKEN_USER is required to verify Telegram Mini App initData")
    if not quantum_bot.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for shared cloud user and signal data")
    quantum_bot.init_db()
    port = int(os.getenv("PORT", "8000"))
    runner = web.AppRunner(create_app(), access_log=log)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Quantum Mini App API listening on port %s", port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
