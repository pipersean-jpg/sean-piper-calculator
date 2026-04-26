from __future__ import annotations

import logging
from functools import wraps

import anthropic
from telegram import Update
from telegram.ext import ContextTypes

from .config import Config
from .intent import ParsedIntent, parse_intent

logger = logging.getLogger(__name__)


def make_handlers(config: Config, anthropic_client: anthropic.AsyncAnthropic):

    def require_auth(func):
        @wraps(func)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            chat_id = update.effective_chat.id
            if chat_id not in config.allowed_chat_ids:
                logger.warning("Ignored message from unauthorised chat %d", chat_id)
                return
            return await func(update, ctx)
        return wrapper

    @require_auth
    async def ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Pong — I'm alive and listening.")

    @require_auth
    async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if not text:
            return

        await update.message.reply_text("Let me go and have a look...")

        try:
            intent = await parse_intent(anthropic_client, text)
        except Exception:
            logger.exception("Intent parse failed for: %r", text)
            await update.message.reply_text(
                "Sorry, something went wrong on my end. Try again?"
            )
            return

        await _respond_to_intent(update, intent, config)

    async def _respond_to_intent(
        update: Update, intent: ParsedIntent, config: Config
    ):
        if not intent.is_confident():
            await update.message.reply_text(
                intent.clarification_needed
                or "Could you give me a bit more detail about what you're looking for?"
            )
            return

        target = intent.human_description()
        quality = intent.min_quality or config.quality.preferred_quality
        size = intent.max_size_gb or config.quality.default_max_size_gb

        # Placeholder until Sonarr/Radarr integration is wired in (step 2)
        await update.message.reply_text(
            f"On it — searching for {target}.\n"
            f"Preferences: {quality} or better, under {size:.1f} GB, "
            f"minimum {config.quality.min_seeders} seeders.\n\n"
            f"_(Download integration not wired yet — confirming intent parsing works.)_",
            parse_mode="Markdown",
        )

    return ping, handle_message
