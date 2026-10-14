"""Shared seam-1 helpers for the node registry and later M3 tasks (test code only: it imports both
``bcs_gs`` and ``bcs_sim``)."""

from __future__ import annotations

import threading
from typing import Any

import paho.mqtt.client as mqtt

# The standard 8 simulated nodes at fixed, distinct positions (metres east / south of the site origin).
STANDARD_8: list[tuple[str, float, float]] = [
    ("water_quality", 50.0, 50.0),
    ("water_quality", 160.0, 250.0),
    ("water_quality", 350.0, 150.0),
    ("water_quality", 250.0, 400.0),
    ("soil_probe", 150.0, 150.0),
    ("soil_probe", 140.0, 260.0),
    ("soil_probe", 150.0, 370.0),
    ("tide_gauge", 250.0, 250.0),
]


def can_connect(broker: Any, user: str, password: str, *, timeout: float = 5.0) -> bool:
    """True when the broker accepts ``user`` / ``password`` (client ID = user name, as nodes do)."""
    done = threading.Event()
    result: dict[str, bool] = {"ok": False}

    def on_connect(_c: Any, _u: Any, _f: Any, rc: Any, _p: Any) -> None:
        result["ok"] = not rc.is_failure
        done.set()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=user, protocol=mqtt.MQTTv5, reconnect_on_failure=False
    )
    client.username_pw_set(user, password)
    client.on_connect = on_connect
    try:
        client.connect(broker.host, broker.port, keepalive=10)
    except OSError:
        return False
    client.loop_start()
    try:
        done.wait(timeout)
        return result["ok"]
    finally:
        client.disconnect()
        client.loop_stop()
