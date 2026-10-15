"""Seam 1: a real Mosquitto with the dynamic-security plugin (addendum G6)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Awaitable, Callable

import paho.mqtt.client as mqtt
import pytest
from bcs_gs.nodes.broker_admin import BrokerAdmin
from bcs_gs.telemetry.mqtt import MqttBus


async def connect_raw(broker, username: str | None, password: str | None = None) -> None:  # type: ignore[no-untyped-def]
    done = threading.Event()
    result: dict[str, object] = {}
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=username or "raw", protocol=mqtt.MQTTv5)
    if username is not None:
        c.username_pw_set(username, password)

    def on_connect(_c, _u, _f, rc, _p):  # type: ignore[no-untyped-def]
        result["rc"] = rc
        done.set()

    c.on_connect = on_connect
    c.connect(broker.host, broker.port)
    c.loop_start()
    try:
        await asyncio.to_thread(done.wait, 5)
    finally:
        c.loop_stop()
        c.disconnect()
    if not done.is_set() or result["rc"].is_failure:  # type: ignore[union-attr]
        raise ConnectionRefusedError(str(result.get("rc")))


def admin_for(broker) -> BrokerAdmin:  # type: ignore[no-untyped-def]
    return BrokerAdmin(broker.host, broker.port, broker.admin_user, broker.admin_password)


async def bus(broker, username: str, password: str) -> MqttBus:  # type: ignore[no-untyped-def]
    b = MqttBus(broker.host, broker.port, username, password, client_id=username)
    await b.connect(timeout=10)
    return b


def collect(sink: list[str]) -> Callable[[str, bytes], Awaitable[None]]:
    async def handler(topic: str, payload: bytes) -> None:
        sink.append(topic)

    return handler


async def eventually(pred: Callable[[], bool], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


async def test_anonymous_client_is_rejected(mosquitto):  # type: ignore[no-untyped-def]
    with pytest.raises(ConnectionRefusedError):
        await connect_raw(mosquitto, username=None)


async def test_node_identity_can_only_publish_its_own_topics(mosquitto):  # type: ignore[no-untyped-def]
    admin = admin_for(mosquitto)
    admin.ensure_service_identity("bcs-gs", "gs-pw")
    admin.ensure_node("WQ-01", "KSL", "n-pw")
    got: list[str] = []
    gs = await bus(mosquitto, "bcs-gs", "gs-pw")
    node = None
    try:
        gs.subscribe("bcs/v1/+/nodes/+/telemetry", collect(got))
        await asyncio.sleep(0.3)
        node = await bus(mosquitto, "WQ-01", "n-pw")
        node.publish("bcs/v1/KSL/nodes/WQ-01/telemetry", b"{}")
        node.publish("bcs/v1/KSL/nodes/WQ-02/telemetry", b"{}")  # denied by ACL
        await eventually(lambda: got == ["bcs/v1/KSL/nodes/WQ-01/telemetry"])
        await asyncio.sleep(0.5)
        assert got == ["bcs/v1/KSL/nodes/WQ-01/telemetry"]
    finally:
        gs.close()
        if node:
            node.close()


async def test_gs_commands_reach_only_the_addressed_node(mosquitto):  # type: ignore[no-untyped-def]
    admin = admin_for(mosquitto)
    admin.ensure_service_identity("bcs-gs", "gs-pw")
    admin.ensure_node("WQ-01", "KSL", "n1")
    admin.ensure_node("WQ-02", "KSL", "n2")
    a: list[str] = []
    b: list[str] = []
    n1 = await bus(mosquitto, "WQ-01", "n1")
    n2 = await bus(mosquitto, "WQ-02", "n2")
    gs = await bus(mosquitto, "bcs-gs", "gs-pw")
    try:
        n1.subscribe("bcs/v1/KSL/nodes/WQ-01/cmd", collect(a))
        n2.subscribe("bcs/v1/KSL/nodes/WQ-01/cmd", collect(b))  # not permitted
        await asyncio.sleep(0.4)
        gs.publish("bcs/v1/KSL/nodes/WQ-01/cmd", b"{}")
        await eventually(lambda: len(a) == 1)
        await asyncio.sleep(0.4)
        assert b == []
    finally:
        for x in (n1, n2, gs):
            x.close()


async def test_disable_node_blocks_login(mosquitto):  # type: ignore[no-untyped-def]
    admin = admin_for(mosquitto)
    admin.ensure_node("WQ-09", "KSL", "pw")
    await connect_raw(mosquitto, "WQ-09", "pw")
    admin.disable_node("WQ-09")
    with pytest.raises(ConnectionRefusedError):
        await connect_raw(mosquitto, "WQ-09", "pw")


def test_ensure_node_is_idempotent(mosquitto):  # type: ignore[no-untyped-def]
    admin = admin_for(mosquitto)
    admin.ensure_node("WQ-01", "KSL", "a")
    admin.ensure_node("WQ-01", "KSL", "b")
    assert admin.list_clients().count("WQ-01") == 1


def test_admin_calls_take_only_their_own_responses(mosquitto):  # type: ignore[no-untyped-def]
    """The broker sends every dynamic-security response to every admin session subscribed to the response
    topic. A call that took the first response would read a concurrent caller's answer (CI: the GS
    re-issuing identities at start while a test listed clients)."""
    import json

    admin = admin_for(mosquitto)
    noise = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="noise", protocol=mqtt.MQTTv5)
    noise.username_pw_set(mosquitto.admin_user, mosquitto.admin_password)
    noise.connect(mosquitto.host, mosquitto.port)
    noise.loop_start()
    stop = threading.Event()

    def flood() -> None:  # another admin session, answered with an error and no data
        other = json.dumps({"commands": [{"command": "getClient", "username": "nobody"}]})
        while not stop.is_set():
            noise.publish("$CONTROL/dynamic-security/v1", other)
            time.sleep(0.001)

    flooder = threading.Thread(target=flood, daemon=True)
    flooder.start()
    try:
        for _ in range(20):
            assert admin.list_clients() == ["admin"]
    finally:
        stop.set()
        flooder.join()
        noise.loop_stop()
        noise.disconnect()



async def test_fallback_bootstrap_admin_is_usable_and_control_only(mosquitto_short_pw):  # type: ignore[no-untyped-def]
    b = mosquitto_short_pw
    assert len(b.admin_password) < 12  # the first-start path is impossible: dynsec init ran
    admin = admin_for(b)
    admin.ensure_node("WQ-01", "KSL", "n-pw")
    assert "WQ-01" in admin.list_clients()
    done, result = threading.Event(), {}
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="a", protocol=mqtt.MQTTv5)
    c.username_pw_set(b.admin_user, b.admin_password)
    c.on_connect = lambda *_: c.subscribe("#", qos=1)
    def on_sub(_c, _u, _mid, rcs, _p):  # type: ignore[no-untyped-def]
        result["rc"] = rcs[0]
        done.set()
    c.on_subscribe = on_sub
    c.connect(b.host, b.port)
    c.loop_start()
    try:
        assert await asyncio.to_thread(done.wait, 5)
    finally:
        c.loop_stop()
        c.disconnect()
    assert result["rc"].is_failure  # the admin cannot read '#'


async def test_connect_returns_at_once_and_retries_until_a_late_broker_is_up(tmp_path):  # type: ignore[no-untyped-def]
    """The bus never blocks the loop on an absent broker; it keeps retrying and then subscribes."""
    import subprocess

    from bcs_gs.broker import bootstrap, find_mosquitto

    exe = find_mosquitto()
    if exe is None:
        pytest.skip("mosquitto binary not found")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    var = tmp_path / "var"
    bootstrap(var, "admin", "late-broker-admin-pw-1", port)  # config only: nothing listens yet
    b = MqttBus("127.0.0.1", port, "bcs-gs", "gs-pw", client_id="bcs-gs")
    acks: list[object] = []
    b._client.on_subscribe = lambda _c, _u, _mid, rcs, _p: acks.append(rcs)
    b.subscribe("bcs/v1/+/late", collect([]))  # registered before any connection exists
    started = time.monotonic()
    await b.connect()
    assert time.monotonic() - started < 1.0 and not b.connected
    await asyncio.sleep(0.5)  # still no broker: the loop is free and nothing has failed hard
    proc = subprocess.Popen(  # noqa: ASYNC220
        [exe, "-c", str(var / "mosquitto" / "mosquitto.conf")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        admin = BrokerAdmin("127.0.0.1", port, "admin", "late-broker-admin-pw-1")
        for _ in range(100):  # the broker needs a moment before the control channel answers
            try:
                admin.ensure_service_identity("bcs-gs", "gs-pw")
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.1)
        await eventually(lambda: b.connected, timeout=20)
        await eventually(lambda: bool(acks), timeout=5)  # subscribed by on_connect
    finally:
        b.close()
        proc.terminate()
        proc.wait(5)


def test_every_connect_resubscribes_even_on_a_resumed_session():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    b = MqttBus("127.0.0.1", 1, "u", "p", client_id="u")
    b._client = MagicMock()
    b.subscribe("a/+", collect([]))  # not connected yet: nothing is sent
    b._client.subscribe.assert_not_called()
    ok = SimpleNamespace(is_failure=False)
    b._on_connect(None, None, SimpleNamespace(session_present=True), ok, None)
    b._client.subscribe.assert_called_once_with("a/+", qos=1)
