from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .config import RadarrConfig, SonarrConfig
from .intent import ParsedIntent

logger = logging.getLogger(__name__)


async def _raise_with_body(r: aiohttp.ClientResponse) -> None:
    if r.status >= 400:
        body = await r.text()
        logger.error("Arr API %s %s → %d: %s", r.method, r.url.path, r.status, body[:500])
        r.raise_for_status()


@dataclass
class GrabResult:
    success: bool
    message: str


class _ArrBase:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/") + "/api/v3"
        self._headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    async def health_check(self) -> list[dict]:
        """Returns list of health issues. Empty = healthy."""
        try:
            issues = await self._get("/health")
            if issues:
                for issue in issues:
                    logger.warning(
                        "Arr health issue [%s] %s: %s",
                        issue.get("type", "?"),
                        issue.get("source", "?"),
                        issue.get("message", "?"),
                    )
            return issues
        except aiohttp.ClientConnectorError:
            raise
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return []

    async def _get(self, path: str, **params: Any) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base}{path}", headers=self._headers, params=params
            ) as r:
                await _raise_with_body(r)
                return await r.json()

    async def _post(self, path: str, body: dict) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}{path}", headers=self._headers, json=body
            ) as r:
                await _raise_with_body(r)
                return await r.json()

    async def _put(self, path: str, body: dict) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self._base}{path}", headers=self._headers, json=body
            ) as r:
                await _raise_with_body(r)
                return await r.json()


class SonarrClient(_ArrBase):
    def __init__(self, cfg: SonarrConfig) -> None:
        super().__init__(cfg.url, cfg.api_key)
        self._quality_profile_id = cfg.quality_profile_id
        self._root_folder = cfg.root_folder

    async def grab(self, intent: ParsedIntent) -> GrabResult:
        term = intent.lookup_term()
        lookup = await self._get("/series/lookup", term=term)
        if not lookup:
            logger.info("Sonarr lookup returned no results for %r", term)
            return GrabResult(False, f'No show found matching "{intent.title}".')

        candidate = lookup[0]
        tvdb_id = candidate["tvdbId"]
        show_title = candidate["title"]
        show_year = candidate.get("year", "")
        logger.info(
            "Sonarr lookup hit: %r (tvdbId=%s, year=%s) for query %r",
            show_title, tvdb_id, show_year, term,
        )

        existing = await self._get("/series")
        series = next((s for s in existing if s["tvdbId"] == tvdb_id), None)

        if series is None:
            logger.info("Series not in library — adding: %r", show_title)
            series = await self._add_series(candidate, intent)
            series_id = series["id"]
            if intent.scope == "specific_episode":
                result = await self._grab_episode_with_retry(
                    series_id, show_title, intent.season, intent.episode
                )
                # Series added unmonitored, nothing to do
                return result
            if intent.scope == "full_season":
                await asyncio.sleep(3)
                return await self._grab_season(series_id, show_title, intent.season)
            # latest_episode — Sonarr needs a moment to load episode list after add
            return await self._grab_latest_with_retry(series_id, show_title)

        series_id = series["id"]
        logger.info("Series already in library: %r (id=%d)", show_title, series_id)

        if intent.scope == "latest_episode":
            result = await self._grab_latest(series_id, show_title)
            await self._unmonitor_series(series_id, show_title)
            return result
        if intent.scope == "specific_episode":
            result = await self._grab_episode(
                series_id, show_title, intent.season, intent.episode
            )
            await self._unmonitor_series(series_id, show_title)
            return result
        if intent.scope == "full_season":
            return await self._grab_season(series_id, show_title, intent.season)
        return GrabResult(False, "Unknown episode scope.")

    # Sonarr v4 MonitorTypes (integers; strings rejected by the API)
    _MONITOR = {"all": 1, "none": 7}

    async def _add_series(self, candidate: dict, intent: ParsedIntent) -> dict:
        # full_season explicitly asks for all episodes — monitor them all.
        # Everything else (latest, specific) — add unmonitored, grab manually.
        monitor_key = "all" if intent.scope == "full_season" else "none"
        clean_candidate = {
            **candidate,
            "seasons": [
                {**s, "monitored": False} for s in candidate.get("seasons", [])
            ],
        }
        return await self._post(
            "/series",
            {
                **clean_candidate,
                "qualityProfileId": self._quality_profile_id,
                "rootFolderPath": self._root_folder,
                "monitored": monitor_key == "all",
                "seasonFolder": True,
                "addOptions": {
                    "monitor": self._MONITOR[monitor_key],
                    "searchForMissingEpisodes": monitor_key == "all",
                    "searchForCutoffUnmetEpisodes": False,
                },
            },
        )

    async def _unmonitor_series(self, series_id: int, title: str) -> None:
        try:
            series = await self._get(f"/series/{series_id}")
            if series.get("monitored"):
                series["monitored"] = False
                await self._put(f"/series/{series_id}", series)
                logger.info("Unmonitored series: %s (id=%d)", title, series_id)
        except Exception as exc:
            logger.warning("Failed to unmonitor series %d: %s", series_id, exc)

    async def _grab_latest(self, series_id: int, title: str) -> GrabResult:
        episodes = await self._get("/episode", seriesId=series_id)
        aired = [e for e in episodes if e.get("airDateUtc") and e["seasonNumber"] > 0]
        if not aired:
            return GrabResult(False, f"No aired episodes found for *{title}*.")

        latest = max(aired, key=lambda e: e["airDateUtc"])
        ep_label = f"S{latest['seasonNumber']:02d}E{latest['episodeNumber']:02d}"
        ep_title = latest.get("title", "")

        await self._put(
            "/episode/monitor", {"episodeIds": [latest["id"]], "monitored": True}
        )
        await self._post(
            "/command", {"name": "EpisodeSearch", "episodeIds": [latest["id"]]}
        )
        logger.info("Sonarr search triggered: %s %s", title, ep_label)

        suffix = f' — "{ep_title}"' if ep_title else ""
        return GrabResult(
            True,
            f"Searching for *{title}* {ep_label}{suffix}.\n"
            f"I'll notify you when it's grabbed.",
        )

    async def _grab_latest_with_retry(
        self,
        series_id: int,
        title: str,
        retries: int = 5,
        delay: float = 4.0,
    ) -> GrabResult:
        for attempt in range(retries):
            result = await self._grab_latest(series_id, title)
            if result.success or attempt == retries - 1:
                return result
            logger.info(
                "Episode list not ready yet (%s), retry %d/%d in %.0fs",
                title, attempt + 1, retries, delay,
            )
            await asyncio.sleep(delay)
        return result  # type: ignore[return-value]

    async def _grab_episode(
        self,
        series_id: int,
        title: str,
        season: int | None,
        episode: int | None,
    ) -> GrabResult:
        if not season or not episode:
            return GrabResult(False, "Need both season and episode number.")

        episodes = await self._get("/episode", seriesId=series_id, seasonNumber=season)
        ep = next((e for e in episodes if e["episodeNumber"] == episode), None)
        if not ep:
            logger.warning(
                "Sonarr episode not found: %s S%02dE%02d (series may still be loading)",
                title, season, episode,
            )
            return GrabResult(
                False,
                f"S{season:02d}E{episode:02d} not found in Sonarr — "
                "the episode list may still be loading. Try again in a moment.",
            )

        await self._put(
            "/episode/monitor", {"episodeIds": [ep["id"]], "monitored": True}
        )
        await self._post(
            "/command", {"name": "EpisodeSearch", "episodeIds": [ep["id"]]}
        )
        logger.info("Sonarr search triggered: %s S%02dE%02d", title, season, episode)
        return GrabResult(
            True,
            f"Searching for *{title}* S{season:02d}E{episode:02d}.\n"
            f"I'll notify you when it's grabbed.",
        )

    async def _grab_episode_with_retry(
        self,
        series_id: int,
        title: str,
        season: int | None,
        episode: int | None,
        retries: int = 5,
        delay: float = 4.0,
    ) -> GrabResult:
        """Retry _grab_episode after a fresh series add — Sonarr loads episode data async."""
        for attempt in range(retries):
            result = await self._grab_episode(series_id, title, season, episode)
            if result.success or attempt == retries - 1:
                return result
            logger.info(
                "Episode not ready yet (%s S%02dE%02d), retry %d/%d in %.0fs",
                title, season or 0, episode or 0, attempt + 1, retries, delay,
            )
            await asyncio.sleep(delay)
        return result  # type: ignore[return-value]

    async def _grab_season(
        self, series_id: int, title: str, season: int | None
    ) -> GrabResult:
        if not season:
            return GrabResult(False, "Need a season number.")
        await self._post(
            "/command",
            {"name": "SeasonSearch", "seriesId": series_id, "seasonNumber": season},
        )
        logger.info("Sonarr season search triggered: %s Season %d", title, season)
        return GrabResult(
            True,
            f"Searching for *{title}* Season {season}.\n"
            f"I'll notify you when releases are grabbed.",
        )

    @staticmethod
    def _scope_label(intent: ParsedIntent) -> str:
        if intent.scope == "latest_episode":
            return "the latest episode"
        if intent.scope == "specific_episode" and intent.season and intent.episode:
            return f"S{intent.season:02d}E{intent.episode:02d}"
        if intent.scope == "full_season" and intent.season:
            return f"Season {intent.season}"
        return "the requested content"


class RadarrClient(_ArrBase):
    def __init__(self, cfg: RadarrConfig) -> None:
        super().__init__(cfg.url, cfg.api_key)
        self._quality_profile_id = cfg.quality_profile_id
        self._root_folder = cfg.root_folder

    async def grab(self, intent: ParsedIntent) -> GrabResult:
        term = intent.lookup_term()
        lookup = await self._get("/movie/lookup", term=term)
        if not lookup:
            logger.info("Radarr lookup returned no results for %r", term)
            return GrabResult(False, f'No movie found matching "{intent.title}".')

        candidate = lookup[0]
        tmdb_id = candidate["tmdbId"]
        movie_title = candidate["title"]
        year = candidate.get("year", "")
        label = f"*{movie_title}*" + (f" ({year})" if year else "")
        logger.info(
            "Radarr lookup hit: %r (tmdbId=%s, year=%s) for query %r",
            movie_title, tmdb_id, year, term,
        )

        existing = await self._get("/movie")
        movie = next((m for m in existing if m["tmdbId"] == tmdb_id), None)

        if movie is None:
            logger.info("Movie not in library — adding: %r", movie_title)
            await self._post(
                "/movie",
                {
                    "tmdbId": tmdb_id,
                    "title": movie_title,
                    "year": year,
                    "qualityProfileId": self._quality_profile_id,
                    "rootFolderPath": self._root_folder,
                    "monitored": True,
                    "addOptions": {"searchForMovie": True},
                },
            )
            return GrabResult(
                True,
                f"Added {label} to Radarr and triggered search.\n"
                f"I'll notify you when a release is grabbed.",
            )

        logger.info("Movie already in library: %r (id=%d)", movie_title, movie["id"])
        await self._post(
            "/command", {"name": "MoviesSearch", "movieIds": [movie["id"]]}
        )
        return GrabResult(
            True,
            f"Searching for {label}.\n"
            f"I'll notify you when a release is grabbed.",
        )
