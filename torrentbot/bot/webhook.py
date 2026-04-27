from __future__ import annotations

import logging

from aiohttp import web

from .notifier import TelegramNotifier
from .qbittorrent_client import QBittorrentClient

logger = logging.getLogger(__name__)


def make_webhook_app(
    notifier: TelegramNotifier,
    qbt: QBittorrentClient,
) -> web.Application:
    app = web.Application()

    async def sonarr_hook(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("Sonarr webhook bad JSON: %s", exc)
            return web.Response(status=400, text="Invalid JSON")

        event = payload.get("eventType", "unknown")
        series_title = payload.get("series", {}).get("title", "?")
        logger.info("Sonarr webhook: event=%s series=%r", event, series_title)

        text = notifier.format_sonarr_event(payload)
        if text:
            await notifier.broadcast(text)

        if event == "Download":
            download_id = payload.get("downloadId", "")
            if download_id:
                await qbt.delete_torrent(download_id)

        return web.Response(status=200, text="ok")

    async def radarr_hook(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("Radarr webhook bad JSON: %s", exc)
            return web.Response(status=400, text="Invalid JSON")

        event = payload.get("eventType", "unknown")
        movie_title = payload.get("movie", {}).get("title", "?")
        logger.info("Radarr webhook: event=%s movie=%r", event, movie_title)

        text = notifier.format_radarr_event(payload)
        if text:
            await notifier.broadcast(text)

        if event == "Download":
            download_id = payload.get("downloadId", "")
            if download_id:
                await qbt.delete_torrent(download_id)

        return web.Response(status=200, text="ok")

    async def health_check(request: web.Request) -> web.Response:
        return web.Response(status=200, text="ok")

    app.router.add_post("/webhooks/sonarr", sonarr_hook)
    app.router.add_post("/webhooks/radarr", radarr_hook)
    app.router.add_get("/health", health_check)

    return app
