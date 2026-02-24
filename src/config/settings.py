from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings

from .schema import BotConfig, FuturesBotConfig


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    kraken_futures_api_key: str = ""
    kraken_futures_api_secret: str = ""
    config_path: str = "config/default.yaml"
    futures_config_path: str = ""
    db_path: str = "data/grid_bot.db"

    model_config = {"env_prefix": "GRIDBOT_", "env_file": ".env"}


def load_config(settings: Settings) -> BotConfig:
    config_file = Path(settings.config_path)
    with open(config_file) as f:
        raw = yaml.safe_load(f)
    return BotConfig(**raw)


def load_futures_config(path: str) -> FuturesBotConfig:
    with open(Path(path)) as f:
        raw = yaml.safe_load(f)
    return FuturesBotConfig(**raw)
