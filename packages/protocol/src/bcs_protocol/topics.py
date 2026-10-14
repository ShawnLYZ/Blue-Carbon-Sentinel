"""MQTT topic helpers: ``bcs/v1/{site_id}/nodes/{node_id}/{channel}`` (addendum G1)."""

from __future__ import annotations

import re

CHANNELS: tuple[str, ...] = ("telemetry", "event", "status", "ack", "cmd", "config")
_SITE_RE = re.compile(r"^[A-Z]{3}$")
_NODE_RE = re.compile(r"^(WQ|SP|TG)-\d{2,3}$")
_PREFIX = "bcs/v1"


def topic(site_id: str, node_id: str, channel: str) -> str:
    """Build a node topic; raises ValueError for a malformed site, node or channel."""
    if not _SITE_RE.fullmatch(site_id):
        raise ValueError(f"invalid site_id: {site_id!r}")
    if not _NODE_RE.fullmatch(node_id):
        raise ValueError(f"invalid node_id: {node_id!r}")
    if channel not in CHANNELS:
        raise ValueError(f"invalid channel: {channel!r}")
    return f"{_PREFIX}/{site_id}/nodes/{node_id}/{channel}"


def parse_topic(topic_str: str) -> tuple[str, str, str]:
    """Split a node topic into ``(site_id, node_id, channel)``; raises ValueError on a foreign topic."""
    parts = topic_str.split("/")
    if len(parts) != 6 or parts[0] != "bcs" or parts[1] != "v1" or parts[3] != "nodes":
        raise ValueError(f"not a Sentinel Protocol v1 topic: {topic_str!r}")
    site_id, node_id, channel = parts[2], parts[4], parts[5]
    if not _SITE_RE.fullmatch(site_id) or not _NODE_RE.fullmatch(node_id) or channel not in CHANNELS:
        raise ValueError(f"not a Sentinel Protocol v1 topic: {topic_str!r}")
    return site_id, node_id, channel
