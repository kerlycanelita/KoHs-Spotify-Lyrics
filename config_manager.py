from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from models import OverlayConfig, default_config


logger = logging.getLogger(__name__)


def _merge_defaults(defaults: dict, current: dict) -> dict:
    merged = defaults.copy()
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merged[key] = _merge_defaults(defaults[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._config = self._load()

    def _load(self) -> OverlayConfig:
        if not self.path.exists():
            config = default_config()
            self._write(config)
            return config

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            defaults = default_config().model_dump(mode="json")
            merged = _merge_defaults(defaults, raw)
            if merged.get("animations", {}).get("song") == "slide":
                merged["animations"]["song"] = "slide_left"
            merged["version"] = defaults["version"]
            config = OverlayConfig.model_validate(merged)
            if merged != raw:
                self._write(config)
            return config
        except Exception:
            backup = self.path.with_name(
                f"config.invalid-{datetime.now():%Y%m%d-%H%M%S}.json"
            )
            try:
                self.path.replace(backup)
                logger.exception("Configuración inválida; guardada en %s", backup)
            except OSError:
                logger.exception("No fue posible respaldar la configuración inválida")
            config = default_config()
            self._write(config)
            return config

    def get(self) -> OverlayConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(self, config: OverlayConfig) -> OverlayConfig:
        with self._lock:
            self._write(config)
            self._config = config
            return self._config.model_copy(deep=True)

    def reset(self) -> OverlayConfig:
        return self.update(default_config())

    def _write(self, config: OverlayConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        payload = json.dumps(
            config.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
