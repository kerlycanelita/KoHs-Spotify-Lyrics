from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config_manager import ConfigManager
from models import FONT_FAMILIES, OverlayConfig, default_config


def test_default_config_is_persisted_and_reloaded(tmp_path):
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    changed = manager.get()
    changed.layout.gap = 31
    manager.update(changed)

    reloaded = ConfigManager(path)
    assert reloaded.get().layout.gap == 31
    assert json.loads(path.read_text(encoding="utf-8"))["layout"]["gap"] == 31


def test_invalid_css_color_is_rejected():
    payload = default_config().model_dump(mode="json")
    payload["current_lyric"]["color"] = "url(javascript:bad)"
    with pytest.raises(ValidationError):
        OverlayConfig.model_validate(payload)


def test_rgba_transparency_is_accepted():
    payload = default_config().model_dump(mode="json")
    payload["layout"]["card"]["background_color"] = "rgba(4, 8, 12, 0.25)"
    parsed = OverlayConfig.model_validate(payload)
    assert parsed.layout.card.background_color.endswith("0.25)")


@pytest.mark.parametrize("font", ["Orbitron", "Playfair Display", "Great Vibes", "Press Start 2P"])
def test_extended_font_catalog_is_accepted(font):
    payload = default_config().model_dump(mode="json")
    payload["title"]["font_family"] = font
    parsed = OverlayConfig.model_validate(payload)
    assert parsed.title.font_family == font


def test_font_catalog_is_large_and_has_no_duplicates():
    assert len(FONT_FAMILIES) >= 80
    assert len(FONT_FAMILIES) == len(set(FONT_FAMILIES))


def test_old_config_is_migrated_without_losing_existing_values(tmp_path):
    path = tmp_path / "config.json"
    old = default_config().model_dump(mode="json")
    old["version"] = 1
    old.pop("translation")
    old.pop("translated_lyric")
    old["layout"]["gap"] = 37
    old["animations"].pop("song_easing")
    old["animations"].pop("song_exit_enabled")
    path.write_text(json.dumps(old), encoding="utf-8")

    migrated = ConfigManager(path).get()

    assert migrated.version == 3
    assert migrated.layout.gap == 37
    assert migrated.translation.enabled is True
    assert migrated.translated_lyric.size == 13
    assert migrated.animations.song_easing == "smooth"


def test_vertical_offsets_are_bounded_and_migrated(tmp_path):
    path = tmp_path / "config.json"
    old = default_config().model_dump(mode="json")
    old["artwork"].pop("offset_y")
    old["layout"].pop("content_offset_y")
    path.write_text(json.dumps(old), encoding="utf-8")

    migrated = ConfigManager(path).get()

    assert migrated.artwork.offset_y == 0
    assert migrated.layout.content_offset_y == 0
