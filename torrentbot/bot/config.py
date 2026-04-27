from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

REQUIRED_VOLUME = "/Volumes/Mac Backup"


@dataclass
class Paths:
    incomplete: str = "/Volumes/Mac Backup/Torrents/incomplete"
    complete: str = "/Volumes/Mac Backup/Torrents/complete"
    tv: str = "/Volumes/Mac Backup/Shared Videos/TV"
    movies: str = "/Volumes/Mac Backup/Shared Videos/Movies"


@dataclass
class PlexConfig:
    url: str = "http://localhost:32400"
    token: str = ""
    tv_library_id: str = "1"
    movies_library_id: str = "2"


@dataclass
class SonarrConfig:
    url: str = "http://localhost:8989"
    api_key: str = ""
    quality_profile_id: int = 4
    root_folder: str = "/Volumes/Mac Backup/Shared Videos/TV"


@dataclass
class RadarrConfig:
    url: str = "http://localhost:7878"
    api_key: str = ""
    quality_profile_id: int = 4
    root_folder: str = "/Volumes/Mac Backup/Shared Videos/Movies"


@dataclass
class ProwlarrConfig:
    url: str = "http://localhost:9696"
    api_key: str = ""


@dataclass
class QBittorrentConfig:
    url: str = "http://localhost:8080"
    username: str = "admin"
    password: str = "adminadmin"


@dataclass
class QualityConfig:
    default_max_size_gb: float = 4.0
    preferred_quality: str = "1080p"
    min_seeders: int = 5


@dataclass
class WebhookConfig:
    port: int = 8765
    host: str = "0.0.0.0"


@dataclass
class Config:
    telegram_token: str
    anthropic_api_key: str
    allowed_chat_ids: list[int]
    paths: Paths = field(default_factory=Paths)
    plex: PlexConfig = field(default_factory=PlexConfig)
    sonarr: SonarrConfig = field(default_factory=SonarrConfig)
    radarr: RadarrConfig = field(default_factory=RadarrConfig)
    prowlarr: ProwlarrConfig = field(default_factory=ProwlarrConfig)
    qbittorrent: QBittorrentConfig = field(default_factory=QBittorrentConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)


def load_config() -> Config:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)

    return Config(
        telegram_token=os.environ["TELEGRAM_TOKEN"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        allowed_chat_ids=[int(i) for i in data.get("allowed_chat_ids", [])],
        paths=Paths(**data.get("paths", {})),
        plex=PlexConfig(**data.get("plex", {})),
        sonarr=SonarrConfig(**data.get("sonarr", {})),
        radarr=RadarrConfig(**data.get("radarr", {})),
        prowlarr=ProwlarrConfig(**data.get("prowlarr", {})),
        qbittorrent=QBittorrentConfig(**data.get("qbittorrent", {})),
        quality=QualityConfig(**data.get("quality", {})),
        webhook=WebhookConfig(**data.get("webhook", {})),
    )
