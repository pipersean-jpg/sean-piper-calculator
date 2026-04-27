from __future__ import annotations

import logging

import aiohttp

from .config import QBittorrentConfig

logger = logging.getLogger(__name__)


class QBittorrentClient:
    def __init__(self, cfg: QBittorrentConfig) -> None:
        self._url = cfg.url.rstrip("/")
        self._username = cfg.username
        self._password = cfg.password

    async def check(self) -> tuple[bool, str]:
        """Returns (reachable, error_message). Empty error = ok."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/api/v2/auth/login",
                    data={"username": self._username, "password": self._password},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as r:
                    body = await r.text()
                    if body.strip() == "Ok.":
                        logger.info("qBittorrent reachable and authenticated")
                        return True, ""
                    if body.strip() == "Fails.":
                        logger.warning("qBittorrent auth rejected (bad credentials)")
                        return False, "qBittorrent credentials rejected — check username/password in config."
                    logger.warning("qBittorrent login unexpected response: %s", body[:100])
                    return False, f"qBittorrent unexpected response: {body[:80]}"
        except aiohttp.ClientConnectorError as exc:
            logger.error("qBittorrent unreachable: %s", exc)
            return False, "qBittorrent not reachable — is it running?"
        except aiohttp.ServerTimeoutError:
            logger.error("qBittorrent connection timed out")
            return False, "qBittorrent timed out."
        except Exception as exc:
            logger.error("qBittorrent check error: %s", exc)
            return False, f"qBittorrent check failed: {exc}"

    async def delete_torrent(self, torrent_hash: str) -> bool:
        """Delete torrent and its files. Returns True on success."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/api/v2/auth/login",
                    data={"username": self._username, "password": self._password},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as r:
                    if (await r.text()).strip() != "Ok.":
                        logger.warning("qBittorrent auth failed for delete")
                        return False

                async with session.post(
                    f"{self._url}/api/v2/torrents/delete",
                    data={"hashes": torrent_hash.lower(), "deleteFiles": "true"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    ok = r.status == 200
                    if ok:
                        logger.info("qBittorrent deleted torrent %s with files", torrent_hash)
                    else:
                        logger.warning("qBittorrent delete returned %d for %s", r.status, torrent_hash)
                    return ok
        except Exception as exc:
            logger.error("qBittorrent delete failed: %s", exc)
            return False
