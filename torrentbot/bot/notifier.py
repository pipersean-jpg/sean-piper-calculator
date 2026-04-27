from __future__ import annotations

import logging

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot: Bot, allowed_chat_ids: list[int]) -> None:
        self._bot = bot
        self._chat_ids = allowed_chat_ids

    async def broadcast(self, text: str) -> None:
        for chat_id in self._chat_ids:
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                logger.exception("Failed to notify chat %d", chat_id)

    # ── Sonarr ──────────────────────────────────────────────────────────────

    def format_sonarr_event(self, payload: dict) -> str | None:
        event = payload.get("eventType", "")
        series = payload.get("series", {})
        title = series.get("title", "Unknown show")

        if event == "Test":
            logger.info("Sonarr webhook test received")
            return "✅ Sonarr webhook connected."

        if event == "Grab":
            episodes = payload.get("episodes", [])
            ep = _ep_label(episodes)
            release = payload.get("release", {})
            quality = release.get("quality", "?")
            indexer = release.get("indexer", "?")
            size_mb = release.get("size", 0) // (1024 * 1024)
            size_str = f", {size_mb} MB" if size_mb else ""
            logger.info("Sonarr grabbed %s %s — %s via %s", title, ep, quality, indexer)
            return f"📥 Grabbed *{title}* {ep}\n{quality} via {indexer}{size_str}"

        if event in ("Download", "EpisodeFileImported"):
            episodes = payload.get("episodes", [])
            ep = _ep_label(episodes)
            is_upgrade = payload.get("isUpgrade", False)
            ef = payload.get("episodeFile", {})
            quality = ef.get("quality", "?")
            verb = "Upgraded" if is_upgrade else "Downloaded"
            logger.info("Sonarr %s %s %s — %s", verb.lower(), title, ep, quality)
            return f"✅ {verb}: *{title}* {ep} ({quality})"

        if event == "ImportComplete":
            episodes = payload.get("episodes", [])
            ep = _ep_label(episodes)
            ef = payload.get("episodeFile", {})
            quality = ef.get("quality", "?")
            logger.info("Sonarr import complete %s %s — %s", title, ep, quality)
            return f"📂 Imported: *{title}* {ep} ({quality})"

        if event == "DownloadFailed":
            episodes = payload.get("episodes", [])
            ep = _ep_label(episodes)
            message = payload.get("message", "unknown reason")
            logger.warning("Sonarr download failed %s %s: %s", title, ep, message)
            return f"❌ Download failed: *{title}* {ep}\n_{message}_"

        if event == "ImportFailed":
            episodes = payload.get("episodes", [])
            ep = _ep_label(episodes)
            message = payload.get("message", "unknown reason")
            logger.warning("Sonarr import failed %s %s: %s", title, ep, message)
            return f"❌ Import failed: *{title}* {ep}\n_{message}_"

        if event == "Health":
            message = payload.get("message", "")
            level = payload.get("level", "warning")
            logger.warning("Sonarr health issue [%s]: %s", level, message)
            if level == "error":
                return f"🚨 Sonarr health error: _{message}_"
            return f"⚠️ Sonarr health warning: _{message}_"

        if event == "HealthRestored":
            message = payload.get("message", "")
            logger.info("Sonarr health restored: %s", message)
            return f"✅ Sonarr health restored: _{message}_"

        logger.debug("Sonarr unhandled event type: %s", event)
        return None

    # ── Radarr ──────────────────────────────────────────────────────────────

    def format_radarr_event(self, payload: dict) -> str | None:
        event = payload.get("eventType", "")
        movie = payload.get("movie", {})
        title = movie.get("title", "Unknown movie")
        year = movie.get("year", "")
        label = f"*{title}*" + (f" ({year})" if year else "")

        if event == "Test":
            logger.info("Radarr webhook test received")
            return "✅ Radarr webhook connected."

        if event == "Grab":
            release = payload.get("release", {})
            quality = release.get("quality", "?")
            indexer = release.get("indexer", "?")
            size_mb = release.get("size", 0) // (1024 * 1024)
            size_str = f", {size_mb} MB" if size_mb else ""
            logger.info("Radarr grabbed %s — %s via %s", title, quality, indexer)
            return f"📥 Grabbed {label}\n{quality} via {indexer}{size_str}"

        if event in ("Download", "MovieFileImported"):
            is_upgrade = payload.get("isUpgrade", False)
            mf = payload.get("movieFile", {})
            quality = mf.get("quality", "?")
            verb = "Upgraded" if is_upgrade else "Downloaded"
            logger.info("Radarr %s %s — %s", verb.lower(), title, quality)
            return f"✅ {verb}: {label} ({quality})"

        if event == "ImportComplete":
            mf = payload.get("movieFile", {})
            quality = mf.get("quality", "?")
            logger.info("Radarr import complete %s — %s", title, quality)
            return f"📂 Imported: {label} ({quality})"

        if event == "DownloadFailed":
            message = payload.get("message", "unknown reason")
            logger.warning("Radarr download failed %s: %s", title, message)
            return f"❌ Download failed: {label}\n_{message}_"

        if event == "ImportFailed":
            message = payload.get("message", "unknown reason")
            logger.warning("Radarr import failed %s: %s", title, message)
            return f"❌ Import failed: {label}\n_{message}_"

        if event == "Health":
            message = payload.get("message", "")
            level = payload.get("level", "warning")
            logger.warning("Radarr health issue [%s]: %s", level, message)
            if level == "error":
                return f"🚨 Radarr health error: _{message}_"
            return f"⚠️ Radarr health warning: _{message}_"

        if event == "HealthRestored":
            message = payload.get("message", "")
            logger.info("Radarr health restored: %s", message)
            return f"✅ Radarr health restored: _{message}_"

        logger.debug("Radarr unhandled event type: %s", event)
        return None


def _ep_label(episodes: list[dict]) -> str:
    if not episodes:
        return ""
    if len(episodes) == 1:
        e = episodes[0]
        s, ep = e.get("seasonNumber", 0), e.get("episodeNumber", 0)
        return f"S{s:02d}E{ep:02d}"
    first, last = episodes[0], episodes[-1]
    s = first.get("seasonNumber", 0)
    return (
        f"S{s:02d}E{first.get('episodeNumber', 0):02d}"
        f"–E{last.get('episodeNumber', 0):02d}"
    )
