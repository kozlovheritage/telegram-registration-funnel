import asyncio
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiohttp import web
from dotenv import load_dotenv

from database import Database

BASE_DIR = Path(__file__).resolve().parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telegram-funnel")


def load_config() -> dict[str, Any]:
    config_path = BASE_DIR / "config.yaml"
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    messages = config.get("follow_up_messages", [])
    if len(messages) != 2:
        raise ValueError("config.yaml must contain exactly two follow_up_messages")
    if any(int(message["delay_seconds"]) < 0 for message in messages):
        raise ValueError("Message delays must be zero or greater")
    return config


def dashboard_url() -> str | None:
    configured_url = os.getenv("WEB_APP_URL", "").strip()
    if configured_url:
        if urlparse(configured_url).scheme == "https":
            return configured_url
        logger.warning("WEB_APP_URL must use HTTPS to open inside Telegram")
        return None

    replit_domain = os.getenv("REPLIT_DEV_DOMAIN", "").strip()
    if replit_domain:
        return f"https://{replit_domain}/"
    return None


def create_router(db: Database, config: dict[str, Any]) -> Router:
    router = Router()
    texts = config["texts"]

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        db.register_start(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await message.answer(texts["welcome"], reply_markup=keyboard)
        await message.answer(texts["request_phone"])

    @router.message(F.contact)
    async def receive_contact(message: Message) -> None:
        if message.from_user is None or message.contact is None:
            return
        if message.contact.user_id != message.from_user.id:
            await message.answer(
                texts["invalid_contact"],
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        is_new_registration = db.register_phone(
            message.from_user.id,
            message.contact.phone_number,
            config["follow_up_messages"],
        )
        if not is_new_registration:
            await message.answer(
                texts["phone_already_received"],
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        web_url = dashboard_url()
        if web_url:
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Открыть дашборд",
                            web_app=WebAppInfo(url=web_url),
                        )
                    ]
                ]
            )
        else:
            reply_markup = None

        await message.answer(
            texts["phone_received"],
            reply_markup=ReplyKeyboardRemove(),
        )
        if reply_markup:
            await message.answer("Статистика воронки:", reply_markup=reply_markup)
        else:
            await message.answer(texts["local_dashboard"])

    return router


async def send_scheduled_messages(bot: Bot, db: Database) -> None:
    while True:
        for scheduled in db.due_messages():
            try:
                await bot.send_message(
                    chat_id=scheduled["user_id"],
                    text=scheduled["text"],
                )
                db.mark_message(scheduled["id"], "sent")
            except Exception:
                logger.exception(
                    "Could not send scheduled message id=%s",
                    scheduled["id"],
                )
                db.mark_message(scheduled["id"], "failed")
        await asyncio.sleep(1)


async def index_handler(_: web.Request) -> web.FileResponse:
    return web.FileResponse(BASE_DIR / "web" / "index.html")


async def stats_handler(request: web.Request) -> web.Response:
    db: Database = request.app["database"]
    return web.json_response(db.dashboard_stats())


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_web_app(db: Database) -> web.Application:
    app = web.Application()
    app["database"] = db
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/stats", stats_handler)
    app.router.add_get("/health", health_handler)
    return app


async def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your bot token."
        )

    config = load_config()
    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path
    db = Database(str(database_path))
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(db, config))

    port = int(os.getenv("PORT", "8000"))
    runner = web.AppRunner(create_web_app(db))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Dashboard is available on port %s", port)

    polling_task = asyncio.create_task(
        dispatcher.start_polling(bot, handle_signals=False)
    )
    message_task = asyncio.create_task(send_scheduled_messages(bot, db))
    try:
        await asyncio.gather(polling_task, message_task)
    finally:
        polling_task.cancel()
        message_task.cancel()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")
