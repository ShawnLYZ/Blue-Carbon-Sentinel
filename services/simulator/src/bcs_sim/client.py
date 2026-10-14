"""Per-node transports (addendum G1, G6): the real MQTT ``NodeClient`` and an in-memory stand-in.

Both satisfy ``NodeLink``; the ``Runtime`` builds one per node through a ``ClientFactory`` called with
keyword arguments ``node_id, password, broker_host, broker_port, site_id, on_cmd, on_config, tap,
clock, status_fields, boot_event``. ``NodeClient`` itself is the default factory; ``MemoryHub().factory``
gives a broker-free transport for the headless runner and unit tests.

Contract of a link:
- ``connect()`` starts connecting (non-blocking); ``wait_connected(timeout)`` waits for it.
- On every successful connect: publish a retained ``online`` status, then the ``boot_event()`` payload
  if it returns one, then subscribe to the node's own ``cmd`` and ``config`` (QoS 1).
- ``publish(channel, payload)``: QoS 1; retained only for ``status``. Ignored while not connected
  (returns False).
- ``drop()``: lose the connection without DISCONNECT so the broker publishes the retained last will
  (``state: offline``, ``reason: last_will``). ``connect()`` may be called again afterwards.
- ``close()``: retained ``offline`` status with ``reason: shutdown``, then a clean DISCONNECT.
- Every message sent is passed to ``tap.emit("up", ...)``, every message received to
  ``tap.emit("down", ...)`` before ``on_cmd`` / ``on_config``. Callbacks may run on a network thread.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from bcs_protocol.generated.status_schema import Status
from bcs_protocol.timefmt import to_iso
from bcs_protocol.topics import topic

from .clock import Clock, SystemClock
from .inspector import InspectorTap
from .nodes.models import FW_VERSION

log = logging.getLogger("bcs_sim.client")

KEEPALIVE_S = 30
SESSION_EXPIRY_S = 3600
MAX_INFLIGHT = 20
QOS = 1

StatusFields = Callable[[], dict[str, Any]]  # {"boot_id", "mode", "interval_s", "fw_version"}
BootEvent = Callable[[], bytes | None]
Inbound = Callable[[bytes], None]


class NodeLink(Protocol):
    node_id: str
    password: str

    @property
    def connected(self) -> bool: ...

    def connect(self) -> None: ...

    def wait_connected(self, timeout: float) -> bool: ...

    def publish(self, channel: str, payload: bytes) -> bool: ...

    def drop(self) -> None: ...

    def close(self) -> None: ...


ClientFactory = Callable[..., NodeLink]


def status_payload(
    site_id: str,
    node_id: str,
    state: str,
    at: datetime,
    reason: str | None,
    fields: dict[str, Any],
) -> bytes:
    """A validated ``bcs.status.v1`` payload; ``mode`` and ``interval_s`` are null when offline."""
    online = state == "online"
    doc = {
        "schema": "bcs.status.v1",
        "site_id": site_id,
        "node_id": node_id,
        "state": state,
        "at": to_iso(at),
        "reason": reason,
        "mode": fields.get("mode") if online else None,
        "interval_s": float(fields["interval_s"]) if online and fields.get("interval_s") else None,
        "fw_version": str(fields.get("fw_version") or FW_VERSION),
        "boot_id": str(fields["boot_id"]),
        "source": "simulated",
        "replay": False,
    }
    return Status.model_validate(doc).model_dump_json(by_alias=True).encode()


def _default_fields() -> StatusFields:
    boot = secrets.token_hex(6)
    return lambda: {"boot_id": boot, "mode": "baseline", "interval_s": None, "fw_version": FW_VERSION}


class _LinkBase:
    def __init__(
        self,
        node_id: str,
        password: str,
        broker_host: str,
        broker_port: int,
        site_id: str,
        on_cmd: Inbound,
        on_config: Inbound,
        tap: InspectorTap | None,
        *,
        clock: Clock | None = None,
        status_fields: StatusFields | None = None,
        boot_event: BootEvent | None = None,
    ) -> None:
        self.node_id = node_id
        self.password = password
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.site_id = site_id
        self.on_cmd = on_cmd
        self.on_config = on_config
        self.tap = tap
        self.clock: Clock = clock or SystemClock()
        self.status_fields: StatusFields = status_fields or _default_fields()
        self.boot_event: BootEvent = boot_event or (lambda: None)

    def topic(self, channel: str) -> str:
        return topic(self.site_id, self.node_id, channel)

    def _status(self, state: str, reason: str | None, at: datetime | None = None) -> bytes:
        return status_payload(
            self.site_id, self.node_id, state, at or self.clock.now(), reason, self.status_fields()
        )

    def _tap(self, direction: str, channel: str, payload: bytes) -> None:
        if self.tap is not None:
            self.tap.emit(direction, self.node_id, channel, self.topic(channel), payload)  # type: ignore[arg-type]

    def _receive(self, channel: str, payload: bytes) -> None:
        self._tap("down", channel, payload)
        handler = self.on_cmd if channel == "cmd" else self.on_config if channel == "config" else None
        if handler is not None:
            try:
                handler(payload)
            except Exception:
                log.exception("%s: inbound %s handler failed", self.node_id, channel)


class NodeClient(_LinkBase):
    """paho MQTT v5 client; client ID = user name = node ID (G1)."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self._client: Any = None
        self._connected = threading.Event()
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def connect(self) -> None:
        import paho.mqtt.client as mqtt
        from paho.mqtt.packettypes import PacketTypes
        from paho.mqtt.properties import Properties

        with self._lock:
            if self._client is not None:
                return
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.node_id, protocol=mqtt.MQTTv5)
            c.username_pw_set(self.node_id, self.password)
            c.max_inflight_messages_set(MAX_INFLIGHT)
            c.reconnect_delay_set(1, 10)
            # The last will carries the connect time (G3); will delay 0 is the default.
            c.will_set(self.topic("status"), self._status("offline", "last_will"), qos=QOS, retain=True)
            c.on_connect = self._on_connect
            c.on_disconnect = self._on_disconnect
            c.on_message = self._on_message
            props = Properties(PacketTypes.CONNECT)
            props.SessionExpiryInterval = SESSION_EXPIRY_S
            c.connect_async(
                self.broker_host, self.broker_port, keepalive=KEEPALIVE_S, clean_start=False, properties=props
            )
            c.loop_start()
            self._client = c

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    def _on_connect(self, c: Any, _u: Any, _flags: Any, rc: Any, _props: Any) -> None:
        if rc.is_failure:
            log.warning("%s: broker refused the connection (%s)", self.node_id, rc)
            return
        self._connected.set()
        try:
            self._send(c, "status", self._status("online", None))
            boot = self.boot_event()
            if boot is not None:
                self._send(c, "event", boot)
        except Exception:  # an exception here would kill paho's network thread
            log.exception("%s: announcing the connection failed", self.node_id)
        c.subscribe([(self.topic("cmd"), QOS), (self.topic("config"), QOS)])

    def _on_disconnect(self, *_a: Any) -> None:
        self._connected.clear()

    def _on_message(self, _c: Any, _u: Any, msg: Any) -> None:
        channel = msg.topic.rsplit("/", 1)[-1]
        self._receive(channel, bytes(msg.payload))

    def _send(self, c: Any, channel: str, payload: bytes) -> Any:
        info = c.publish(self.topic(channel), payload, qos=QOS, retain=channel == "status")
        self._tap("up", channel, payload)
        return info

    def publish(self, channel: str, payload: bytes) -> bool:
        c = self._client
        if c is None or not self.connected:
            return False
        self._send(c, channel, payload)
        return True

    def drop(self) -> None:
        """Stop the network loop and close the socket without DISCONNECT: the last will fires."""
        with self._lock:
            c, self._client = self._client, None
        self._connected.clear()
        if c is None:
            return
        c.loop_stop()
        sock = c.socket()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def close(self, timeout: float = 2.0) -> None:
        with self._lock:
            c, self._client = self._client, None
        if c is None:
            return
        if self.connected:
            try:
                self._send(c, "status", self._status("offline", "shutdown")).wait_for_publish(timeout)
            except (RuntimeError, ValueError):
                pass
            c.disconnect()
        c.loop_stop()
        self._connected.clear()


# ---- in-memory transport ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MemoryMessage:
    topic: str
    node_id: str
    channel: str
    payload: bytes
    retain: bool


class MemoryLink(_LinkBase):
    def __init__(self, hub: MemoryHub, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.hub = hub
        self._connected = False
        self._will: bytes | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            return
        self._will = self._status("offline", "last_will")
        self._connected = True
        self.publish("status", self._status("online", None))
        boot = self.boot_event()
        if boot is not None:
            self.publish("event", boot)
        cfg = self.hub.retained.get(self.topic("config"))
        if cfg is not None:
            self._receive("config", cfg)

    def wait_connected(self, timeout: float) -> bool:
        return self._connected

    def publish(self, channel: str, payload: bytes) -> bool:
        if not self._connected:
            return False
        self.hub._record(self, channel, payload)
        self._tap("up", channel, payload)
        return True

    def drop(self) -> None:
        if not self._connected:
            return
        self._connected = False
        if self._will is not None:
            self.hub._record(self, "status", self._will)  # the broker publishes the last will

    def close(self) -> None:
        if self._connected:
            self.publish("status", self._status("offline", "shutdown"))
        self._connected = False


class MemoryHub:
    """A broker stand-in: records what nodes publish, keeps retained messages, delivers cmd/config."""

    def __init__(self) -> None:
        self.published: list[MemoryMessage] = []
        self.retained: dict[str, bytes] = {}
        self.links: dict[str, MemoryLink] = {}
        self._lock = threading.Lock()

    def factory(self, **kw: Any) -> MemoryLink:
        link = MemoryLink(self, **kw)
        self.links[link.node_id] = link
        return link

    def _record(self, link: MemoryLink, channel: str, payload: bytes) -> None:
        t = link.topic(channel)
        retain = channel == "status"
        with self._lock:
            self.published.append(MemoryMessage(t, link.node_id, channel, bytes(payload), retain))
            if retain:
                self.retained[t] = bytes(payload)

    def deliver(self, node_id: str, channel: str, payload: bytes) -> bool:
        """Ground Station -> node. ``config`` is also kept retained. False when the node is absent/offline."""
        link = self.links.get(node_id)
        if channel == "config" and link is not None:
            self.retained[link.topic("config")] = bytes(payload)
        if link is None or not link.connected:
            return False
        link._receive(channel, bytes(payload))
        return True
