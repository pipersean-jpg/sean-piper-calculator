from __future__ import annotations

import asyncio
import logging
from functools import wraps

import anthropic
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from .arr_client import GrabResult, RadarrClient, SonarrClient
from .config import Config
from .intent import ParsedIntent, parse_intent
from .prowlarr_client import IndexerHealth, ProwlarrClient
from .qbittorrent_client import QBittorrentClient

logger = logging.getLogger(__name__)


def make_handlers(config: Config, anthropic_client: anthropic.AsyncAnthropic):
    sonarr = SonarrClient(config.sonarr)
    radarr = RadarrClient(config.radarr)
    prowlarr = ProwlarrClient(config.prowlarr)
    qbt = QBittorrentClient(config.qbittorrent)

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
        await update.message.reply_text("Pong — alive and listening.")

    @require_auth
    async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if not text:
            return

        await update.message.reply_text("On it, checking...")

        # Parse intent and run health checks in parallel.
        intent_task = asyncio.create_task(parse_intent(anthropic_client, text))
        health_task = asyncio.create_task(
            _run_health_checks(sonarr, radarr, qbt, prowlarr)
        )

        try:
            intent, health = await asyncio.gather(intent_task, health_task)
        except Exception:
            logger.exception("Intent parse failed for: %r", text)
            await update.message.reply_text(
                "Something went wrong parsing your request. Try again?"
            )
            return

        logger.info(
            "Parsed intent: kind=%s title=%r year=%s scope=%s season=%s episode=%s confidence=%.2f",
            intent.kind, intent.title, intent.year, intent.scope,
            intent.season, intent.episode, intent.confidence,
        )

        if not intent.is_confident():
            await update.message.reply_text(
                intent.clarification_needed
                or "Could you give me a bit more detail about what you're looking for?"
            )
            return

        warnings, fatal = health
        if fatal:
            await update.message.reply_text(fatal)
            return

        app_name = "Sonarr" if intent.kind == "tv" else "Radarr"
        await update.message.reply_text(
            f"Looking up {intent.human_description()} in {app_name}..."
        )

        try:
            result = await _grab(intent, sonarr, radarr)
        except aiohttp.ClientConnectorError as exc:
            logger.error("%s not reachable: %s", app_name, exc)
            await update.message.reply_text(
                f"{app_name} isn't reachable right now. Is it running?"
            )
            return
        except aiohttp.ClientResponseError as exc:
            logger.error("Arr API error %d: %s", exc.status, exc.message)
            if exc.status == 401:
                msg = "Auth failed — check the API key in config.yaml."
            elif exc.status == 400:
                msg = "Bad request to Sonarr/Radarr — check bot logs for details."
            else:
                msg = f"Arr API error {exc.status} — check bot logs."
            await update.message.reply_text(msg)
            return
        except Exception:
            logger.exception("Grab failed for intent: %r", intent)
            await update.message.reply_text(
                "Something went wrong triggering the download. Check the bot logs."
            )
            return

        reply = result.message
        if not result.success:
            reply += (
                "\n\nI've left it monitored so Sonarr/Radarr will grab it "
                "automatically when an acceptable release appears."
            )
            if warnings:
                reply += f"\n\n{warnings}"

        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            logger.warning("Markdown reply failed, retrying as plain text")
            await update.message.reply_text(reply.replace("*", ""))

    return ping, handle_message


async def _grab(
    intent: ParsedIntent, sonarr: SonarrClient, radarr: RadarrClient
) -> GrabResult:
    if intent.kind == "tv":
        return await sonarr.grab(intent)
    if intent.kind == "movie":
        return await radarr.grab(intent)
    return GrabResult(
        False,
        "Couldn't tell if this is a show or a movie. Try again with more detail.",
    )


async def _run_health_checks(
    sonarr: SonarrClient,
    radarr: RadarrClient,
    qbt: QBittorrentClient,
    prowlarr: ProwlarrClient,
) -> tuple[str, str]:
    """
    Returns (warning_text, fatal_text).
    fatal_text is non-empty only if qBittorrent is down (Sonarr/Radarr can't complete).
    warning_text is advisory (degraded indexers, arr health issues).
    """
    sonarr_task = asyncio.create_task(_arr_health("Sonarr", sonarr))
    radarr_task = asyncio.create_task(_arr_health("Radarr", radarr))
    qbt_task = asyncio.create_task(qbt.check())
    prowlarr_task = asyncio.create_task(prowlarr.indexer_health())

    (sonarr_ok, sonarr_warn), (radarr_ok, radarr_warn), \
        (qbt_ok, qbt_err), indexer_health = await asyncio.gather(
            sonarr_task, radarr_task, qbt_task, prowlarr_task
        )

    logger.info(
        "Health: sonarr_ok=%s radarr_ok=%s qbt_ok=%s indexers=%s",
        sonarr_ok, radarr_ok, qbt_ok, indexer_health.summary(),
    )

    warnings: list[str] = []
    if sonarr_warn:
        warnings.append(sonarr_warn)
    if radarr_warn:
        warnings.append(radarr_warn)
    indexer_warn = indexer_health.telegram_warning()
    if indexer_warn:
        warnings.append(indexer_warn)

    fatal = ""
    if not qbt_ok:
        fatal = f"⚠️ {qbt_err}\nSonarr/Radarr won't be able to send downloads until qBittorrent is reachable."

    return "\n".join(warnings), fatal


async def _arr_health(name: str, client: SonarrClient | RadarrClient) -> tuple[bool, str]:
    try:
        issues = await client.health_check()
        if not issues:
            return True, ""
        errors = [i for i in issues if i.get("type") == "error"]
        warnings = [i for i in issues if i.get("type") == "warning"]
        parts: list[str] = []
        if errors:
            parts.append(f"{len(errors)} error(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        return True, f"⚠️ {name} has {', '.join(parts)} — check {name} for details."
    except aiohttp.ClientConnectorError:
        logger.error("%s unreachable during health check", name)
        return False, f"⚠️ {name} is not reachable."
    except Exception as exc:
        logger.warning("%s health check error: %s", name, exc)
        return True, ""
