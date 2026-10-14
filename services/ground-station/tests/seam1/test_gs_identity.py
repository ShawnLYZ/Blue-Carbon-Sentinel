"""The Ground Station creates its own broker identity at startup (task 13 ruling)."""

import asyncio
from pathlib import Path

from bcs_gs.core.config import load_settings
from bcs_gs.nodes.gs_identity import ensure_gs_identity
from bcs_gs.telemetry.mqtt import MqttBus

REPO_ROOT = Path(__file__).resolve().parents[4]


def _settings(broker, **kw):
    return load_settings(
        REPO_ROOT, env_file=None, broker_port=broker.port, broker_admin_user=broker.admin_user,
        broker_admin_password=broker.admin_password, **kw,
    )  # fmt: skip


async def test_gs_identity_is_created_and_can_log_in(mosquitto):
    s = _settings(mosquitto, gs_mqtt_password="gs-secret-password-1")
    assert await ensure_gs_identity(s, max_attempts=1) is True
    bus = MqttBus("127.0.0.1", mosquitto.port, "bcs-gs", "gs-secret-password-1", "bcs-gs")
    await bus.connect(timeout=10)  # raises if refused
    bus.close()


async def test_gs_identity_skipped_without_credentials(mosquitto):
    s = load_settings(REPO_ROOT, env_file=None, broker_port=mosquitto.port)
    assert await ensure_gs_identity(s, max_attempts=1) is False


async def test_gs_identity_gives_up_quietly_when_broker_is_down():
    s = load_settings(
        REPO_ROOT, env_file=None, broker_port=1, broker_admin_password="x" * 16, gs_mqtt_password="y" * 16
    )
    assert await ensure_gs_identity(s, max_attempts=1) is False


async def test_preflight_broker_probe_logs_in_as_the_ensured_identity(mosquitto, tmp_path):
    from bcs_gs.status.probes import RealProbes

    s = _settings(mosquitto, gs_mqtt_password="gs-secret-password-1")
    assert await ensure_gs_identity(s, max_attempts=1) is True
    probes = RealProbes(tmp_path)
    assert probes.broker_login("127.0.0.1", mosquitto.port, "bcs-gs", "gs-secret-password-1") is True
    assert probes.broker_login("127.0.0.1", mosquitto.port, "bcs-gs", "wrong-password-xx") is False


async def test_preflight_probe_does_not_kick_a_held_gs_session(mosquitto, tmp_path):
    from bcs_gs.status.probes import RealProbes

    s = _settings(mosquitto, gs_mqtt_password="gs-secret-password-1")
    assert await ensure_gs_identity(s, max_attempts=1) is True
    bus = MqttBus("127.0.0.1", mosquitto.port, "bcs-gs", "gs-secret-password-1", "bcs-gs")
    drops: list[int] = []
    original = bus._on_disconnect
    bus._client.on_disconnect = lambda *a: (drops.append(1), original())  # type: ignore[assignment]
    await bus.connect(timeout=10)
    try:
        # Let the session settle (the broker may drop sessions right after an identity change).
        for _ in range(100):
            await asyncio.sleep(0.1)
            before = len(drops)
            await asyncio.sleep(0.4)
            if bus.connected and len(drops) == before:
                break
        assert bus.connected
        probes = RealProbes(tmp_path)
        assert probes.broker_login("127.0.0.1", mosquitto.port, "bcs-gs", "gs-secret-password-1") is True
        await asyncio.sleep(1)
        assert bus.connected and len(drops) == before
    finally:
        bus.close()
