from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from .config import ProwlarrConfig

logger = logging.getLogger(__name__)


@dataclass
class IndexerHealth:
    healthy: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    unreachable: bool = False

    @property
    def degraded(self) -> bool:
        return bool(self.blocked or self.disabled or self.unreachable)

    @property
    def has_any_healthy(self) -> bool:
        return bool(self.healthy) and not self.unreachable

    def telegram_warning(self) -> str | None:
        if self.unreachable:
            return "⚠️ Prowlarr unreachable — search may fail if Sonarr/Radarr have no cached indexers."
        if not self.degraded:
            return None
        parts: list[str] = []
        if self.blocked:
            parts.append(f"blocked: {', '.join(self.blocked)}")
        if self.disabled:
            parts.append(f"disabled: {', '.join(self.disabled)}")
        return f"⚠️ Some indexers unavailable ({'; '.join(parts)}). Search coverage may be limited."

    def summary(self) -> str:
        if self.unreachable:
            return "Prowlarr unreachable"
        return (
            f"{len(self.healthy)} healthy, "
            f"{len(self.blocked)} blocked, "
            f"{len(self.disabled)} disabled"
        )


class ProwlarrClient:
    def __init__(self, cfg: ProwlarrConfig) -> None:
        self._base = cfg.url.rstrip("/") + "/api/v1"
        self._headers = {"X-Api-Key": cfg.api_key}

    async def indexer_health(self) -> IndexerHealth:
        try:
            indexers, statuses = await self._get_indexers_and_statuses()
        except aiohttp.ClientConnectorError as exc:
            logger.error("Prowlarr unreachable: %s", exc)
            return IndexerHealth(unreachable=True)
        except Exception as exc:
            logger.warning("Prowlarr health check failed: %s", exc)
            return IndexerHealth(unreachable=True)

        blocked_ids = {s["indexerId"] for s in statuses}

        health = IndexerHealth()
        for ix in indexers:
            name = ix.get("name", f"id={ix.get('id', '?')}")
            if not ix.get("enable", True):
                health.disabled.append(name)
                logger.info("Prowlarr indexer disabled: %s", name)
            elif ix.get("id") in blocked_ids:
                health.blocked.append(name)
                logger.warning("Prowlarr indexer blocked: %s", name)
            else:
                health.healthy.append(name)

        logger.info("Prowlarr indexers — %s", health.summary())

        for s in statuses:
            ix_name = next(
                (ix.get("name", "?") for ix in indexers if ix.get("id") == s["indexerId"]),
                f"id={s['indexerId']}",
            )
            reason = s.get("mostRecentFailure", "unknown")
            logger.warning("Prowlarr blocked indexer %s — last failure: %s", ix_name, reason)

        return health

    async def _get_indexers_and_statuses(self) -> tuple[list[dict], list[dict]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base}/indexer",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                r.raise_for_status()
                indexers = await r.json()

            async with session.get(
                f"{self._base}/indexerstatus",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                r.raise_for_status()
                statuses = await r.json()

        return indexers, statuses
