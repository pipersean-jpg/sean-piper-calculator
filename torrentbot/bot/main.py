from __future__ import annotations

import logging
import sys
from pathlib import Path

import anthropic
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .config import REQUIRED_VOLUME, load_config
from .handlers import make_handlers

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
            "Required volume not mounted: %s\n"
            "Plug in the drive and restart the bot.",
            REQUIRED_VOLUME,
        )
        sys.exit(1)
    logger.info("Volume confirmed: %s", REQUIRED_VOLUME)


def main():
    _assert_volume_mounted()

    config = load_config()
    anthropic_client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    ping_handler, message_handler = make_handlers(config, anthropic_client)

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(CommandHandler("ping", ping_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info(
        "TorrentBot started. Authorised chats: %s", config.allowed_chat_ids
    )
    app.run_polling()


if __name__ == "__main__":
    main()
