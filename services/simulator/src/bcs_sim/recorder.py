"""Session record and replay (addendum K5).

``Recorder`` listens to the inspector tap and writes every outgoing ("up") ``telemetry`` and ``event``
message as it was actually published (after faults) to ``<sessions_dir>/<stamp>-<name>.jsonl``:

- line 1: ``{"kind": "bcs.sim-session.v1", "name", "created_at", "seed", "nodes": [{node_id, node_type, e_m, s_m}]}``
- then: ``{"t_ms", "node_id", "channel", "payload"}`` (``payload`` is the JSON object, or the raw text
  when the message was not JSON, e.g. a ``malformed`` fault).

``status`` (connection state) and ``ack`` (bound to live command IDs) are not recorded. ``stop()`` uploads
the file through the Ground Station (I4); a failed upload keeps the local file and is reported in the
``SessionMeta``, which is also written next to the file as ``<stem>.meta.json`` (``sidecar_path``).

``Replayer`` re-publishes a session through the live node links at the recorded offsets, driven by
``step(now)``. Each payload is re-stamped: ``sampled_at`` / ``at`` = now, a fresh ``boot_id`` per node,
``seq`` restarting at 0 per node and channel, ``replay: true`` and ``source: "simulated"``. Lines for nodes
that are not in the runtime are skipped; non-JSON lines are re-sent unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from bcs_protocol.timefmt import to_iso

from .clock import Clock
from .config import REPO_ROOT
from .inspector import InspectorPacket, InspectorTap

log = logging.getLogger("bcs_sim.recorder")
KIND = "bcs.sim-session.v1"
RECORDED_CHANNELS = ("telemetry", "event")
DEFAULT_SESSIONS_DIR = REPO_ROOT / "var" / "sessions"


class SessionUploader(Protocol):
    def upload_session(self, meta: dict[str, Any], path: Path) -> Any: ...


@dataclass
class SessionMeta:
    id: str
    name: str
    path: Path
    created_at: str
    seed: int | None
    duration_s: float
    message_count: int
    nodes: list[dict[str, Any]] = field(default_factory=list)
    kind: str = "recording"
    uploaded: bool = False
    upload_error: str | None = None

    def upload_fields(self) -> dict[str, Any]:
        """The ``sim_sessions`` row fields (H2) sent with the upload."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "name": self.name,
            "kind": self.kind,
            "seed": self.seed,
            "duration_s": self.duration_s,
            "message_count": self.message_count,
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:60] or "session"


class Recorder:
    def __init__(
        self,
        clock: Clock,
        tap: InspectorTap,
        gs: SessionUploader | None,
        *,
        seed: int | None,
        nodes: Callable[[], list[dict[str, Any]]],
        sessions_dir: Path | None = None,
    ) -> None:
        self.clock = clock
        self.gs = gs
        self.seed = seed
        self._nodes = nodes
        self.sessions_dir = Path(sessions_dir) if sessions_dir is not None else DEFAULT_SESSIONS_DIR
        self._lock = threading.Lock()
        self._fh: Any = None
        self._meta: SessionMeta | None = None
        self._started: datetime | None = None
        tap.add_listener(self._on_packet)

    @property
    def active(self) -> bool:
        return self._fh is not None

    @property
    def current_path(self) -> Path | None:
        """The file being written, while recording."""
        m = self._meta
        return m.path if m is not None and self.active else None

    def status(self) -> dict[str, Any] | None:
        """K1 ``recording``: null when idle."""
        m = self._meta
        if m is None or not self.active:
            return None
        return {"id": m.id, "name": m.name, "started_at": m.created_at, "messages": m.message_count}

    def start(self, name: str) -> SessionMeta:
        # The node list first, outside our lock: it takes the runtime lock, and a stepping runtime holds
        # that lock while it publishes into _on_packet (which takes ours). Lock order: runtime, recorder.
        nodes = self._nodes()
        with self._lock:
            if self._fh is not None:
                raise RuntimeError("a recording is already running")
            now = self.clock.now()
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            path = self.sessions_dir / f"{now:%Y%m%dT%H%M%S}-{_slug(name)}-{secrets.token_hex(2)}.jsonl"
            header = {
                "kind": KIND,
                "name": name,
                "created_at": to_iso(now),
                "seed": self.seed,
                "nodes": nodes,
            }
            fh = path.open("w", encoding="utf-8", newline="\n")
            fh.write(json.dumps(header) + "\n")
            self._fh = fh
            self._started = now
            self._meta = SessionMeta(str(uuid.uuid4()), name, path, to_iso(now), self.seed, 0.0, 0, nodes)
            return self._meta

    def _on_packet(self, p: InspectorPacket) -> None:
        if p.direction != "up" or p.channel not in RECORDED_CHANNELS:
            return
        with self._lock:
            if self._fh is None or self._meta is None or self._started is None:
                return
            t_ms = max(0, round((p.at - self._started).total_seconds() * 1000))
            line = {"t_ms": t_ms, "node_id": p.node_id, "channel": p.channel, "payload": p.payload}
            self._fh.write(json.dumps(line) + "\n")
            self._meta.message_count += 1

    def stop(self) -> SessionMeta:
        with self._lock:
            if self._fh is None or self._meta is None or self._started is None:
                raise RuntimeError("no recording is running")
            self._fh.close()
            self._fh = None
            meta = self._meta
            meta.duration_s = round((self.clock.now() - self._started).total_seconds(), 3)
        if self.gs is not None:
            try:
                self.gs.upload_session(meta.upload_fields(), meta.path)
                meta.uploaded = True
            except Exception as exc:  # noqa: BLE001 - the local file stays; the caller sees why
                meta.upload_error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("session upload failed: %s", meta.upload_error)
        try:
            sidecar_path(meta.path).write_text(json.dumps(meta.to_dict()), encoding="utf-8")
        except OSError as exc:
            log.warning("session metadata not written: %s", exc)
        return meta


def sidecar_path(session_path: Path) -> Path:
    """``<stem>.meta.json`` next to a session file: its ``SessionMeta`` (id, upload state) once stopped."""
    p = Path(session_path)
    return p.with_name(p.stem + ".meta.json")


# ---- replay -------------------------------------------------------------------------------------------
Publish = Callable[[str, str, bytes], bool]  # (node_id, channel, payload) -> sent?


@dataclass
class _Line:
    t_ms: int
    node_id: str
    channel: str
    payload: Any


class Replayer:
    def __init__(self, clock: Clock, publish: Publish, known_nodes: Callable[[], set[str]]) -> None:
        self.clock = clock
        self._publish = publish
        self._known = known_nodes
        self._lock = threading.Lock()
        self._lines: list[_Line] = []
        self._next = 0
        self._start: datetime | None = None
        self._path: Path | None = None
        self._boot: dict[str, str] = {}
        self._seq: dict[tuple[str, str], int] = {}
        self.sent = 0

    @property
    def active(self) -> bool:
        return self._start is not None

    @property
    def node_ids(self) -> set[str]:
        return {ln.node_id for ln in self._lines} if self.active else set()

    def status(self) -> dict[str, Any] | None:
        """K1 ``replay``: null when idle."""
        if not self.active or self._path is None:
            return None
        return {"path": str(self._path), "sent": self.sent, "total": len(self._lines)}

    def replay(self, session_path: str | Path) -> None:
        path = Path(session_path)
        rows = path.read_text(encoding="utf-8").splitlines()
        if not rows or json.loads(rows[0]).get("kind") != KIND:
            raise ValueError(f"not a {KIND} file: {path.name}")
        lines = []
        for row in rows[1:]:
            if row.strip():
                d = json.loads(row)
                lines.append(_Line(int(d["t_ms"]), str(d["node_id"]), str(d["channel"]), d["payload"]))
        lines.sort(key=lambda ln: ln.t_ms)
        with self._lock:
            self._lines, self._next, self._path = lines, 0, path
            self._boot = {n: secrets.token_hex(6) for n in {ln.node_id for ln in lines}}
            self._seq = {}
            self.sent = 0
            self._start = self.clock.now()

    def stop(self) -> None:
        with self._lock:
            self._start = None
            self._lines, self._next = [], 0

    def _restamp(self, ln: _Line, now: datetime) -> bytes:
        p = ln.payload
        if not isinstance(p, dict):
            return str(p).encode("utf-8")
        doc = dict(p)
        stamp = to_iso(now)
        for k in ("sampled_at", "at"):
            if k in doc:
                doc[k] = stamp
        if "boot_id" in doc:
            doc["boot_id"] = self._boot[ln.node_id]
        if "seq" in doc:
            key = (ln.node_id, ln.channel)
            doc["seq"] = self._seq.get(key, 0)
            self._seq[key] = doc["seq"] + 1
        doc["replay"] = True
        doc["source"] = "simulated"
        return json.dumps(doc).encode()

    def step(self, now: datetime) -> int:
        """Publish every line due by ``now``; returns how many were sent. Ends after the last line."""
        with self._lock:
            if self._start is None:
                return 0
            elapsed_ms = (now - self._start).total_seconds() * 1000
            due: list[_Line] = []
            while self._next < len(self._lines) and self._lines[self._next].t_ms <= elapsed_ms:
                due.append(self._lines[self._next])
                self._next += 1
            known = self._known()
            out = [(ln, self._restamp(ln, now)) for ln in due if ln.node_id in known]
            if self._next >= len(self._lines):
                self._start = None
        n = 0
        for ln, payload in out:
            if self._publish(ln.node_id, ln.channel, payload):
                n += 1
        self.sent += n
        return n
