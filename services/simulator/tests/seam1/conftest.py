"""Seam-1 fixtures for the simulator: a fake Ground Station client over the repo-root ``mosquitto``."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import helpers
from sim_world import sim_world  # noqa: F401  (Task 12: GS + broker + simulator API)


@pytest.fixture
def fake_gs_with_8_nodes(mosquitto: Any) -> Iterator[helpers.FakeGs]:
    """WQ-01..04, SP-01..03 and TG-01 at fixed positions; credentials provision the fixture broker."""
    try:
        yield helpers.FakeGs(mosquitto)
    finally:
        helpers.cleanup()
