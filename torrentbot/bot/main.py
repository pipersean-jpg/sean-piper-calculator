from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import anthropic
from aiohttp import web
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .config import REQUIRED_VOLUME, load_config
from .handlers import make_handlers
from .notifier import TelegramNotifier
from .qbittorrent_client import QBittorrentClient
from .webhook import make_webhook_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _assert_volume_mounted():
    volume = Path(REQUIRED_VOLUME)
    if not volume.exists():
        logger.error(
            "Required volume not mounted: %s\nPlug in the drive and restart.",
            REQUIRED_VOLUME,
        )
        sys.exit(1)
    logger.info("Volume confirmed: %s", REQUIRED_VOLUME)


async def _run():
    _assert_volume_mounted()

    config = load_config()
    anthropic_client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    # Build Telegram application.
    tg_app = Application.builder().token(config.telegram_token).build()

    # Notifier needs the bot handle from the Application.
    notifier = TelegramNotifier(tg_app.bot, config.allowed_chat_ids)
    qbt = QBittorrentClient(config.qbittorrent)

    ping_handler, message_handler = make_handlers(config, anthropic_client)
    tg_app.add_handler(CommandHandler("ping", ping_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Build webhook server (aiohttp).
    webhook_app = make_webhook_app(notifier, qbt)
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, config.webhook.host, config.webhook.port)

    stop_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)

        await site.start()
        logger.info(
            "TorrentBot started. Authorised chats: %s. "
            "Webhook server on %s:%d",
            config.allowed_chat_ids,
            config.webhook.host,
            config.webhook.port,
        )
        logger.info(
            "Configure Sonarr/Radarr webhook → http://<this-host>:%d/webhooks/sonarr "
            "and .../webhooks/radarr",
            config.webhook.port,
        )

        await stop_event.wait()

        logger.info("Shutting down...")
        await tg_app.updater.stop()
        await tg_app.stop()

    await runner.cleanup()
    logger.info("Stopped.")


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
