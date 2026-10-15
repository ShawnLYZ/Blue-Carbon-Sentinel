"""Idempotent broker identity management over ``$CONTROL/dynamic-security/v1`` (addendum G6)."""

from __future__ import annotations

import json
import secrets
import threading
from typing import Any

import paho.mqtt.client as mqtt

CONTROL = "$CONTROL/dynamic-security/v1"
GS_ROLE = "bcs-gs-service"
_GS_SUBSCRIBE = ("telemetry", "event", "status", "ack")
_GS_PUBLISH = ("cmd", "config")
_NODE_SEND = ("telemetry", "event", "status", "ack")
_NODE_RECEIVE = ("cmd", "config")
_TIMEOUT = 10.0
_BENIGN = ("already exists", "already assigned", "already has")


class BrokerAdminError(RuntimeError):
    pass


def _acl(acltype: str, topic: str) -> dict[str, Any]:
    return {"acltype": acltype, "topic": topic, "priority": 0, "allow": True}


class BrokerAdmin:
    """One short-lived admin connection per call; every operation can be repeated safely."""

    def __init__(self, host: str, port: int, admin_user: str, admin_password: str) -> None:
        self._host, self._port = host, port
        self._user, self._password = admin_user, admin_password

    # ---- transport ---------------------------------------------------------------------------
    def _send(self, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # The broker sends every response to every admin session subscribed to the response topic, so a
        # concurrent caller's answer can arrive first. Tag our commands and take only the reply echoing it.
        token = secrets.token_hex(8)
        tagged = [{**cmd, "correlationData": token} for cmd in commands]
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="", protocol=mqtt.MQTTv5, reconnect_on_failure=False
        )
        client.username_pw_set(self._user, self._password)
        ready, answered = threading.Event(), threading.Event()
        state: dict[str, Any] = {}

        def on_connect(c: Any, _u: Any, _f: Any, rc: Any, _p: Any) -> None:
            if rc.is_failure:
                state["error"] = f"admin connect refused: {rc}"
                ready.set()
                return
            c.subscribe(f"{CONTROL}/response", qos=1)

        def on_subscribe(_c: Any, _u: Any, _mid: Any, _rcs: Any, _p: Any) -> None:
            ready.set()

        def on_message(_c: Any, _u: Any, msg: Any) -> None:
            try:
                responses = json.loads(msg.payload)["responses"]
            except (ValueError, KeyError, TypeError):
                return
            if answered.is_set() or not any(r.get("correlationData") == token for r in responses):
                return
            state["responses"] = responses
            answered.set()

        client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
        try:
            client.connect(self._host, self._port, keepalive=30)
        except OSError as exc:
            raise BrokerAdminError(f"broker unreachable: {exc}") from exc
        client.loop_start()
        try:
            if not ready.wait(_TIMEOUT) or "error" in state:
                raise BrokerAdminError(state.get("error", "admin connect timed out"))
            client.publish(CONTROL, json.dumps({"commands": tagged}), qos=1)
            if not answered.wait(_TIMEOUT):
                raise BrokerAdminError("no dynamic-security response")
        finally:
            client.disconnect()
            client.loop_stop()
        return list(state["responses"])

    def _run(self, commands: list[dict[str, Any]], tolerate: tuple[str, ...] = ()) -> list[Any]:
        """Send commands; ignore errors containing a tolerated phrase; raise on any other."""
        out = self._send(commands)
        data: list[Any] = []
        for cmd, resp in zip(commands, out, strict=False):
            err = resp.get("error")
            if err and not any(t in err.lower() for t in tolerate):
                raise BrokerAdminError(f"{cmd['command']}: {err}")
            data.append(resp.get("data"))
        return data

    # ---- identities ----------------------------------------------------------------------------
    def _ensure_client(
        self,
        username: str,
        password: str,
        role: str,
        acls: list[dict[str, Any]],
        *,
        bind_clientid: bool = True,
    ) -> None:
        self._run(
            [
                {
                    "command": "setDefaultACLAccess",
                    "acls": [
                        {"acltype": "publishClientSend", "allow": False},
                        {"acltype": "publishClientReceive", "allow": False},
                        {"acltype": "subscribe", "allow": False},
                        {"acltype": "unsubscribe", "allow": True},
                    ],
                },
                {"command": "createRole", "rolename": role},
                *({"command": "addRoleACL", "rolename": role, **a} for a in acls),
                {
                    "command": "createClient",
                    "username": username,
                    "password": password,
                    **({"clientid": username} if bind_clientid else {}),
                },
                {"command": "setClientPassword", "username": username, "password": password},
                # Service identities carry no client-id binding (G6): a second session must not take over.
                *(
                    []
                    if bind_clientid
                    else [{"command": "setClientId", "username": username, "clientid": ""}]
                ),
                {"command": "enableClient", "username": username},
            ],
            tolerate=_BENIGN,
        )
        # Adding a role twice answers "Internal error", so look first.
        (client,) = self._run([{"command": "getClient", "username": username}])
        if role not in [r["rolename"] for r in (client or {}).get("client", {}).get("roles", [])]:
            self._run([{"command": "addClientRole", "username": username, "rolename": role}])

    def ensure_service_identity(self, username: str, password: str) -> None:
        acls = [
            *(_acl("subscribeLiteral", f"bcs/v1/+/nodes/+/{c}") for c in _GS_SUBSCRIBE),
            *(_acl("publishClientReceive", f"bcs/v1/+/nodes/+/{c}") for c in _GS_SUBSCRIBE),
            *(_acl("publishClientSend", f"bcs/v1/+/nodes/+/{c}") for c in _GS_PUBLISH),
        ]
        self._ensure_client(username, password, GS_ROLE, acls, bind_clientid=False)

    def ensure_node(self, node_id: str, site_id: str, password: str) -> None:
        base = f"bcs/v1/{site_id}/nodes/{node_id}"
        acls = [
            *(_acl("publishClientSend", f"{base}/{c}") for c in _NODE_SEND),
            *(_acl("subscribeLiteral", f"{base}/{c}") for c in _NODE_RECEIVE),
            *(_acl("publishClientReceive", f"{base}/{c}") for c in _NODE_RECEIVE),
        ]
        self._ensure_client(node_id, password, f"node-{node_id}", acls)

    def set_password(self, username: str, password: str) -> None:
        self._run([{"command": "setClientPassword", "username": username, "password": password}])

    def disable_node(self, node_id: str) -> None:
        self._run([{"command": "disableClient", "username": node_id}])

    def list_clients(self) -> list[str]:
        (data,) = self._run([{"command": "listClients"}])
        return list(data.get("clients", []))
