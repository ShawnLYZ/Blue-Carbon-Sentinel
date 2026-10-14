"""Parse and validate Sentinel Protocol v1 messages (addendum G2-G5, steps 1, 2 and 4).

Wraps the generated Pydantic models and adds what JSON Schema cannot express: strict typing,
calendar-valid timestamps, the 2 KB event ``details`` cap and per-type command ``params``.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from .generated.ack_schema import Ack
from .generated.cmd_schema import Command
from .generated.config_schema import NodeConfig
from .generated.event_schema import NodeEvent
from .generated.status_schema import Status
from .generated.telemetry_schema import Telemetry
from .timefmt import from_iso

__all__ = [
    "READING_KEYS",
    "VALIDATION_RANGES",
    "Ack",
    "Command",
    "NodeConfig",
    "NodeEvent",
    "ProtocolError",
    "Status",
    "Telemetry",
    "dedupe_key",
    "parse_message",
]

# Addendum G4: reading keys per node type and physical validation ranges (not health bands).
READING_KEYS: dict[str, tuple[str, ...]] = {
    "water_quality": ("salinity_psu", "turbidity_ntu", "do_mg_l", "temp_c", "ph"),
    "soil_probe": ("porewater_salinity_psu", "soil_moisture_pct"),
    "tide_gauge": ("water_level_cm",),
}
VALIDATION_RANGES: dict[str, tuple[float, float]] = {
    "salinity_psu": (0, 60),
    "turbidity_ntu": (0, 4000),
    "do_mg_l": (0, 20),
    "temp_c": (0, 45),
    "ph": (0, 14),
    "porewater_salinity_psu": (0, 120),
    "soil_moisture_pct": (0, 100),
    "water_level_cm": (-500, 500),
}

_MODELS: dict[str, type[BaseModel]] = {
    "telemetry": Telemetry,
    "status": Status,
    "event": NodeEvent,
    "cmd": Command,
    "ack": Ack,
    "config": NodeConfig,
}
_TIME_FIELDS = ("sampled_at", "at", "issued_at", "expires_at")
_EVENT_DETAILS_MAX_BYTES = 2048
_SET_MODE_KEYS = ("mode", "duration_s", "interval_s")


class ProtocolError(Exception):
    """A message failed parsing or validation; ``errors`` lists human-readable reasons."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _fmt(exc: ValidationError, prefix: str = "") -> list[str]:
    out = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{prefix}{loc}: {err['msg']}" if loc else f"{prefix.rstrip('.')}: {err['msg']}")
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not allowed")


def parse_message(channel: str, payload: bytes) -> BaseModel:
    """Parse ``payload`` for ``channel`` into its model; raise ``ProtocolError`` on any failure."""
    model = _MODELS.get(channel)
    if model is None:
        raise ProtocolError([f"channel: unknown channel {channel!r}"])
    try:
        text = payload.decode("utf-8")
        raw = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError([f"payload: not valid JSON ({exc})"]) from exc
    if not isinstance(raw, dict):
        raise ProtocolError(["payload: JSON value must be an object"])
    try:
        msg = model.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise ProtocolError(_fmt(exc)) from exc

    errors = _check_times(raw)
    inner = getattr(msg, "root", msg)
    if getattr(inner, "replay", False) and inner.source != "simulated":
        errors.append("replay: true is only allowed when source is 'simulated'")
    if isinstance(msg, Status) and msg.state == "offline" and msg.mode is not None:
        errors.append("mode: must be null when state is 'offline'")
    if isinstance(msg, NodeEvent):
        size = len(json.dumps(raw["details"], separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > _EVENT_DETAILS_MAX_BYTES:
            errors.append(f"details: {size} bytes serialised exceeds {_EVENT_DETAILS_MAX_BYTES}")
    elif isinstance(msg, Command):
        errors += _check_command_params(msg)
    if errors:
        raise ProtocolError(errors)
    return msg


def _check_times(raw: dict[str, Any]) -> list[str]:
    errors = []
    for key in _TIME_FIELDS:
        value = raw.get(key)
        if isinstance(value, str):
            try:
                from_iso(value)
            except ValueError:
                errors.append(f"{key}: {value!r} is not a valid calendar time")
    return errors


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _check_command_params(cmd: Command) -> list[str]:
    params, ctype = cmd.params, cmd.type
    if ctype in ("ping", "reboot"):
        return [] if not params else [f"params: must be empty for {ctype}"]
    if ctype == "set_mode":
        errors = [f"params.{k}: unexpected field" for k in params if k not in _SET_MODE_KEYS]
        mode = params.get("mode")
        if mode is None:
            errors.append("params.mode: required")
        elif mode not in ("baseline", "investigation"):
            errors.append("params.mode: must be 'baseline' or 'investigation'")
        duration = params.get("duration_s")
        if duration is None:
            if mode == "investigation":
                errors.append("params.duration_s: required when mode is 'investigation'")
        elif not (_is_num(duration) and duration > 0):
            errors.append("params.duration_s: must be a number greater than 0")
        interval = params.get("interval_s")
        if interval is not None and not (_is_num(interval) and interval > 0):
            errors.append("params.interval_s: must be a number greater than 0")
        return errors
    # set_config: a non-empty partial of the config fields that a command may change.
    errors = []
    if not params:
        errors.append("params: set_config needs at least one config field")
    for key, value in params.items():
        info = NodeConfig.model_fields.get(key)
        if info is None or key in ("schema_", "site_id", "node_id", "config_version", "issued_at"):
            errors.append(f"params.{key}: not a configurable field")
            continue
        try:
            TypeAdapter(Annotated[info.annotation, info]).validate_python(value, strict=True)
        except ValidationError as exc:
            errors += [f"params.{key}: {e['msg']}" for e in exc.errors(include_url=False)]
    return errors


def dedupe_key(msg: BaseModel) -> tuple[str, str, int]:
    """The (node, boot, seq) dedupe key of a telemetry or event message (addendum G5.6)."""
    inner = getattr(msg, "root", msg)
    try:
        return (inner.node_id, inner.boot_id, inner.seq)
    except AttributeError as exc:
        raise TypeError(f"{type(inner).__name__} has no (boot_id, seq) dedupe key") from exc
