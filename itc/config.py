"""Loads config.yaml and the OpenRouter key from the environment or a local .env file."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_api_key() -> str | None:
    """Environment variable wins over .env; returns None when no key is configured."""
    key = os.environ.get("OPENROUTER_API_KEY") or _read_dotenv(ROOT / ".env").get("OPENROUTER_API_KEY")
    return key or None
