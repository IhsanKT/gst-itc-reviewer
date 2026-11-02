"""On-disk response cache. Re-running the eval or the UI on the same inputs costs zero API calls.

Key = sha256 of (model_id, prompt_version, rule_pack_version, temperature, messages, run_index). The messages
contain the rule pack text, the client profile and the batch of invoice lines, so any change to them misses.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def cache_key(model_id: str, prompt_version: str, rule_pack_version: str, temperature: float,
              messages: list[dict], run_index: int) -> str:
    payload = json.dumps(
        [model_id, prompt_version, rule_pack_version, temperature, messages, run_index],
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, key: str, record: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {**record, "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._path(key).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
