"""The alert rules (spec 25): severity, dedupe key and dedupe window per alert type."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["info", "warning", "critical"]
# (zone_id, node_id, details) -> the key duplicates share
DedupeKey = Callable[[str | None, str | None, dict[str, Any]], str]


@dataclass(frozen=True)
class AlertRule:
    severity: Severity
    dedupe_key: DedupeKey
    window_s: int | None  # None: a duplicate counts only while the alert is unacknowledged


def _zone(type_: str) -> DedupeKey:
    return lambda zone, _node, _d: f"{type_}|{zone or ''}"


def _node(type_: str) -> DedupeKey:
    return lambda _zone, node, _d: f"{type_}|{node or ''}"


def _node_parameter(type_: str) -> DedupeKey:
    return lambda _zone, node, d: f"{type_}|{node or ''}|{d.get('parameter') or ''}"


def _detail(type_: str, field: str) -> DedupeKey:
    return lambda _zone, _node, d: f"{type_}|{d.get(field) or ''}"


def _single(type_: str) -> DedupeKey:
    return lambda _zone, _node, _d: type_


ZONE_WINDOW_S = 900
NODE_ANOMALY_WINDOW_S = 300

ALERT_RULES: dict[str, AlertRule] = {
    "zone_flagged": AlertRule("warning", _zone("zone_flagged"), ZONE_WINDOW_S),
    "early_warning": AlertRule("warning", _zone("early_warning"), ZONE_WINDOW_S),
    "risk_critical": AlertRule("critical", _zone("risk_critical"), None),
    "node_anomaly": AlertRule("warning", _node_parameter("node_anomaly"), NODE_ANOMALY_WINDOW_S),
    "node_offline": AlertRule("critical", _node("node_offline"), None),
    "node_low_battery": AlertRule("warning", _node("node_low_battery"), None),
    "camera_offline": AlertRule("critical", _single("camera_offline"), None),
    "camera_online": AlertRule("info", _single("camera_online"), None),
    "cloud_offline": AlertRule("warning", _single("cloud_offline"), None),
    "ai_degraded": AlertRule(
        "info", _detail("ai_degraded", "role"), None
    ),  # warning when the rules tier answered
    "coverage_gap": AlertRule("warning", _zone("coverage_gap"), None),
    "task_started": AlertRule("info", _detail("task_started", "task_id"), None),
    "task_ended": AlertRule("info", _detail("task_ended", "task_id"), None),
    "ledger_issued": AlertRule("info", _detail("ledger_issued", "record_id"), None),  # M6: per record
    "chain_broken": AlertRule("critical", _single("chain_broken"), None),  # M6
}
