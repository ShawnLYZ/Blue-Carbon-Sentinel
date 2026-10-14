"""Seam 2: the rendered Mosquitto config (Review Focus 5)."""

from __future__ import annotations

from pathlib import Path

from bcs_gs.broker import render_config


def test_rendered_config_quotes_paths_with_spaces(tmp_path: Path) -> None:
    d = tmp_path / "Blue Carbon Sentinel" / "var"
    conf = render_config(d, 1883)
    assert "allow_anonymous false" in conf and "listener 1883 0.0.0.0" in conf
    assert str(d / "mosquitto" / "dynamic-security.json") in conf
    assert "per_listener_settings false" in conf and "persistence true" in conf
