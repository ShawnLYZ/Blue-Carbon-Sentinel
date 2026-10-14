"""MQTT v5 bus over paho (addendum G1). Handlers run on the asyncio loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

Handler = Callable[[str, bytes], Awaitable[None]]
KEEPALIVE_S = 30
SESSION_EXPIRY_S = 3600
MAX_INFLIGHT = 20
RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 30


class MqttBus:
    def __init__(self, host: str, port: int, username: str, password: str, client_id: str) -> None:
        self._host, self._port = host, port
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5
        )
        self._client.username_pw_set(username, password)
        self._client.max_inflight_messages_set(MAX_INFLIGHT)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._subs: dict[str, Handler] = {}
        self._connected = threading.Event()
        self._refused: str | None = None
        self._sub_lock = threading.Lock()
        self._pending_subs: set[int] = set()
        self._subscribed = threading.Event()  # every registered filter acknowledged on this connection
        self.connected = False

    def set_will(self, topic: str, payload: bytes) -> None:
        """Retained last will (QoS 1, delay 0). Call before ``connect``."""
        props = Properties(PacketTypes.WILLMESSAGE)
        props.WillDelayInterval = 0
        self._client.will_set(topic, payload, qos=1, retain=True, properties=props)

    async def connect(self, timeout: float | None = None) -> None:
        """Start the network thread and connect without blocking the event loop.

        paho connects asynchronously and keeps retrying with back-off (``RECONNECT_MIN_S`` up to
        ``RECONNECT_MAX_S``) until connected or ``close`` is called, so the Ground Station can start
        before the broker is up. With ``timeout`` this waits (off the loop) for the first connection
        and raises ``ConnectionError`` if it is refused or not reached in time; the bus then stops.
        Without it, returns at once. Stores the running loop for handler dispatch.
        """
        self._loop = asyncio.get_running_loop()
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = SESSION_EXPIRY_S
        self._client.reconnect_delay_set(RECONNECT_MIN_S, RECONNECT_MAX_S)
        self._client.connect_async(
            self._host, self._port, keepalive=KEEPALIVE_S, clean_start=False, properties=props
        )
        self._client.loop_start()
        if timeout is None:
            return
        if not await asyncio.to_thread(self._connected.wait, timeout) or self._refused:
            self._client.loop_stop()
            raise ConnectionError(self._refused or "MQTT connect timed out")

    def close(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
        self.connected = False

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Register a handler; subscribed now if connected, else on the next (re)connect."""
        self._subs[pattern] = handler
        if self.connected:
            self._send_subscribe(pattern)

    async def wait_subscribed(self, timeout: float) -> bool:
        """True once connected and every registered filter has been acknowledged (SUBACK)."""
        return await asyncio.to_thread(self._subscribed.wait, timeout)

    def _send_subscribe(self, pattern: str) -> None:
        with self._sub_lock:
            self._subscribed.clear()
            result = self._client.subscribe(pattern, qos=1)  # (rc, mid)
            mid = result[1] if isinstance(result, tuple) and len(result) == 2 else None
            if mid is not None:
                self._pending_subs.add(mid)

    def publish(self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False) -> None:
        self._client.publish(topic, payload, qos=qos, retain=retain)

    # ---- paho callbacks (network thread) -------------------------------------------------------
    def _on_connect(self, _c: Any, _u: Any, flags: Any, rc: Any, _p: Any) -> None:
        if rc.is_failure:
            self._refused = f"MQTT connect refused: {rc}"
        else:
            self._refused = None
            self.connected = True
            # Every (re)connect, not only a fresh session: subscriptions must survive a broker restart
            # or a dropped session, and re-subscribing on a resumed session is harmless.
            with self._sub_lock:
                self._pending_subs.clear()
            for pattern in list(self._subs):
                self._send_subscribe(pattern)
            if not self._subs:
                self._subscribed.set()
        self._connected.set()

    def _on_subscribe(self, _c: Any, _u: Any, mid: int, _rcs: Any, _p: Any) -> None:
        with self._sub_lock:
            self._pending_subs.discard(mid)
            if not self._pending_subs:
                self._subscribed.set()

    def _on_disconnect(self, *_args: Any) -> None:
        self.connected = False
        self._subscribed.clear()

    def _on_message(self, _c: Any, _u: Any, msg: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        for pattern, handler in list(self._subs.items()):
            if mqtt.topic_matches_sub(pattern, msg.topic):
                loop.call_soon_threadsafe(self._spawn, handler, msg.topic, bytes(msg.payload))
                break  # one delivery per message even when filters overlap

    def _spawn(self, handler: Handler, topic: str, payload: bytes) -> None:
        task = asyncio.get_running_loop().create_task(handler(topic, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
