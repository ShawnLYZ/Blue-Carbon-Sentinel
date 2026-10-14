"""Preflight: the go/no-go check list (addendum I3 order, design section 32).

Each check returns pass, warn or fail with a fix hint. Checks run in parallel (every network probe
has a 5 s timeout) and a probe that raises becomes a ``fail``; nothing here can crash the caller.
Key values never appear in a check: only the slot name (for example ``BCS_GEMINI_API_KEY_2``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.core.config import Settings
from bcs_gs.models_paths import DEPTH_MODEL_FILES, depth_model_dir
from bcs_gs.status.probes import Probes

log = logging.getLogger("bcs_gs.status")

REPO_ROOT = Path(__file__).resolve().parents[5]
DASHBOARD_HOME = "https://supabase.com/dashboard/projects"
BROKER_USER = "bcs-gs"
DB_WARN_BYTES = 400_000_000
DB_FAIL_BYTES = 500_000_000  # the free-tier database limit
DISK_WARN_BYTES = 5_000_000_000
DISK_FAIL_BYTES = 1_000_000_000

C = m.PreflightCheck


def state_root(settings: Settings) -> Path:
    return settings.data_dir or REPO_ROOT


def project_ref(supabase_url: str | None) -> str | None:
    """The project ref is the subdomain of BCS_SUPABASE_URL (``https://<ref>.supabase.co``)."""
    match = re.match(r"https://([a-z0-9-]+)\.supabase\.co\b", supabase_url or "")
    return match.group(1) if match else None


def dashboard_url(settings: Settings) -> str:
    """The project's dashboard page, or the project list when BCS_SUPABASE_URL names no project."""
    ref = project_ref(settings.supabase_url)
    return f"https://supabase.com/dashboard/project/{ref}" if ref else DASHBOARD_HOME


@dataclass
class Facts:
    """Measured values the status service shows beside the checks."""

    db_bytes: int | None = None
    paused: bool | None = None
    camera_ip: str | None = None
    camera_json: dict[str, Any] | None = None
    directml: bool | None = None
    values: dict[str, Any] = field(default_factory=dict)


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class _Runner:
    def __init__(self, settings: Settings, probes: Probes) -> None:
        self.s = settings
        self.p = probes
        self.root = state_root(settings)
        self.dashboard = dashboard_url(settings)
        self.facts = Facts()

    # 1 -----------------------------------------------------------------------------------
    def camera(self) -> m.PreflightCheck:
        host = self.s.camera_host
        hint = f"Power the camera, join it to the same Wi-Fi, and check BCS_CAMERA_HOST ({host}) in .env."
        ip = self.p.resolve_camera(host)
        if ip is None:
            return C(id="camera", label="SentinelCam", status="fail",
                     detail=f"{host} did not resolve.", fix_hint=hint)  # fmt: skip
        self.facts.camera_ip = ip
        info = self.p.camera_status(ip)
        if info is None:
            return C(id="camera", label="SentinelCam", status="fail",
                     detail=f"Resolved to {ip} but /status did not answer.", fix_hint=hint)  # fmt: skip
        self.facts.camera_json = info
        fw = info.get("fw_version")
        return C(id="camera", label="SentinelCam", status="pass",
                 detail=f"{info.get('device_id', 'camera')} at {ip}" + (f", firmware {fw}." if fw else "."))  # fmt: skip

    # 2 -----------------------------------------------------------------------------------
    def broker(self) -> m.PreflightCheck:
        pw = self.s.gs_mqtt_password
        if pw is None:
            return C(id="broker", label="MQTT broker", status="fail",
                     detail="No broker password for the Ground Station.",
                     fix_hint="Set BCS_GS_MQTT_PASSWORD in .env and run the launcher.")  # fmt: skip
        if self.p.broker_login("127.0.0.1", self.s.broker_port, BROKER_USER, pw.get_secret_value()):
            return C(id="broker", label="MQTT broker", status="pass",
                     detail=f"Logged in as {BROKER_USER} on port {self.s.broker_port}.")  # fmt: skip
        return C(id="broker", label="MQTT broker", status="fail",
                 detail=f"Login as {BROKER_USER} on port {self.s.broker_port} failed.",
                 fix_hint="Start the stack with the launcher; if it is running, check BCS_GS_MQTT_PASSWORD.")  # fmt: skip

    # 3 -----------------------------------------------------------------------------------
    def broker_port(self) -> m.PreflightCheck:
        port = self.s.broker_port
        owner = self.p.port_owner(port)
        label = f"Broker port {port}"
        if owner == "ours":
            return C(id="broker_port", label=label, status="pass", detail="Held by our Mosquitto.")
        if owner == "free":
            return C(id="broker_port", label=label, status="warn", detail="Nothing is listening.",
                     fix_hint="Start the stack with the launcher.")  # fmt: skip
        return C(id="broker_port", label=label, status="fail",
                 detail=f"Another process holds port {port}.",
                 fix_hint="If the Windows Mosquitto service is running, stop and disable the Mosquitto "
                          "service (services.msc), then run the launcher again.")  # fmt: skip

    # 4 -----------------------------------------------------------------------------------
    def supabase(self) -> m.PreflightCheck:
        s = self.s
        label = "Supabase"
        if not (s.supabase_url and s.supabase_service_role_key):
            return C(id="supabase", label=label, status="fail",
                     detail="Supabase URL or service role key is missing; cloud sync is disabled.",
                     fix_hint="Set BCS_SUPABASE_URL and BCS_SUPABASE_SERVICE_ROLE_KEY in .env.")  # fmt: skip
        if s.supabase_access_token is None:
            return C(id="supabase", label=label, status="warn",
                     detail="Credentials are set; the paused or active state is unknown.",
                     fix_hint="Set SUPABASE_ACCESS_TOKEN in .env to read the project state.")  # fmt: skip
        ref = project_ref(s.supabase_url)
        if ref is None:
            return C(id="supabase", label=label, status="warn",
                     detail="BCS_SUPABASE_URL does not name a project; the paused or active state is unknown.",
                     fix_hint="Set BCS_SUPABASE_URL to the project URL, https://<project-ref>.supabase.co.")  # fmt: skip
        status = self.p.supabase_project_status(ref, s.supabase_access_token.get_secret_value())
        if status == "ACTIVE_HEALTHY":
            self.facts.paused = False
            return C(id="supabase", label=label, status="pass", detail="Project is active.")
        if status == "INACTIVE":
            self.facts.paused = True
            return C(id="supabase", label=label, status="fail",
                     detail="The project is paused.",
                     fix_hint=f"Restore it at {self.dashboard}. Work is buffered locally meanwhile.")  # fmt: skip
        return C(id="supabase", label=label, status="warn",
                 detail="Project state could not be read.",
                 fix_hint=f"Check SUPABASE_ACCESS_TOKEN and your connection, or open {self.dashboard}.")  # fmt: skip

    # 5 -----------------------------------------------------------------------------------
    def cloud_usage(self) -> m.PreflightCheck:
        size = self.p.db_size()
        self.facts.db_bytes = size
        label = "Cloud database size"
        if size is None:
            return C(id="cloud_usage", label=label, status="warn",
                     detail="Database size is unavailable.",
                     fix_hint=f"Needs the cloud to be reachable; see {self.dashboard}.")  # fmt: skip
        detail = f"{size / 1e6:.0f} MB of 500 MB."
        if size >= DB_FAIL_BYTES:
            return C(id="cloud_usage", label=label, status="fail", detail=detail,
                     fix_hint=f"Free-tier limit reached. Prune data at {self.dashboard}.")  # fmt: skip
        if size >= DB_WARN_BYTES:
            return C(id="cloud_usage", label=label, status="warn", detail=detail,
                     fix_hint=f"Approaching the 500 MB free-tier limit. See {self.dashboard}.")  # fmt: skip
        return C(id="cloud_usage", label=label, status="pass", detail=detail)

    # 6 -----------------------------------------------------------------------------------
    def gemini_keys(self) -> m.PreflightCheck:
        s = self.s
        slots = [(1, s.gemini_api_key_1), (2, s.gemini_api_key_2), (3, s.gemini_api_key_3)]
        label = "Gemini keys"
        missing = [f"BCS_GEMINI_API_KEY_{n}" for n, k in slots if k is None]
        if len(missing) == 3:
            return C(id="gemini_keys", label=label, status="fail", detail="No Gemini keys are set.",
                     fix_hint="Add BCS_GEMINI_API_KEY_1 to .env; the rules tier is used meanwhile.")  # fmt: skip
        rejected = [
            f"BCS_GEMINI_API_KEY_{n}" for n, k in slots if k is not None
            and not self.p.gemini_models(k.get_secret_value())
        ]  # fmt: skip
        working = 3 - len(missing) - len(rejected)
        if working == 0:
            return C(id="gemini_keys", label=label, status="fail",
                     detail="Every Gemini key was rejected or unreachable.",
                     fix_hint=f"Check {', '.join(rejected)} in .env and your connection.")  # fmt: skip
        problems = [f"{r} rejected" for r in rejected] + [f"{x} not set" for x in missing]
        if problems:
            return C(id="gemini_keys", label=label, status="warn",
                     detail=f"{working} of 3 keys work.",
                     fix_hint="; ".join(problems) + ".")  # fmt: skip
        return C(id="gemini_keys", label=label, status="pass", detail="3 of 3 keys work.")

    # 7 -----------------------------------------------------------------------------------
    def nvidia_key(self) -> m.PreflightCheck:
        key = self.s.nvidia_api_key
        label = "NVIDIA key"
        if key is None:
            return C(id="nvidia_key", label=label, status="fail",
                     detail="No NVIDIA key; future illustrations use the code-only repaint.",
                     fix_hint="Add BCS_NVIDIA_API_KEY to .env.")  # fmt: skip
        if not self.p.nvidia_auth(key.get_secret_value()):
            return C(id="nvidia_key", label=label, status="fail",
                     detail="BCS_NVIDIA_API_KEY was rejected or unreachable.",
                     fix_hint="Check BCS_NVIDIA_API_KEY in .env and your connection.")  # fmt: skip
        return C(id="nvidia_key", label=label, status="pass", detail="Key accepted.")

    # 8 -----------------------------------------------------------------------------------
    def mapbox_token(self) -> m.PreflightCheck:
        token = self.s.mapbox_public_token
        label = "Mapbox token"
        if token is None:
            return C(id="mapbox_token", label=label, status="fail",
                     detail="No Mapbox public token; the map shows an unavailable message.",
                     fix_hint="Add BCS_MAPBOX_PUBLIC_TOKEN to .env.")  # fmt: skip
        if not self.p.mapbox_token(token.get_secret_value()):
            return C(id="mapbox_token", label=label, status="fail",
                     detail="BCS_MAPBOX_PUBLIC_TOKEN was rejected or unreachable.",
                     fix_hint="Check BCS_MAPBOX_PUBLIC_TOKEN in .env and your connection.")  # fmt: skip
        return C(id="mapbox_token", label=label, status="pass", detail="Token accepted.")

    # 9 -----------------------------------------------------------------------------------
    def depth_model(self) -> m.PreflightCheck:
        folder = depth_model_dir(self.root)
        label = "Depth model"
        if not any(self.p.depth_model_present(folder / f) for f in DEPTH_MODEL_FILES):
            return C(id="depth_model", label=label, status="fail",
                     detail=f"No depth model in {folder.relative_to(self.root).as_posix()}.",
                     fix_hint="Run `bcs-gs fetch-models` to download it.")  # fmt: skip
        dml = self.p.directml_available()
        self.facts.directml = dml
        if not dml:
            return C(id="depth_model", label=label, status="warn",
                     detail="Model present, but DirectML is unavailable; depth would run on the CPU.",
                     fix_hint="Install onnxruntime-directml (uv sync) and update the GPU driver.")  # fmt: skip
        return C(id="depth_model", label=label, status="pass", detail="Model present; DirectML available.")

    # 10 ----------------------------------------------------------------------------------
    def ollama(self) -> m.PreflightCheck:
        label = "Ollama"
        want = self.s.ai.models.get("gemma_local", "gemma4")
        models = self.p.ollama_models()
        hint = f"Start Ollama and run `ollama pull {want}` to enable the local Gemma tier."
        if models is None:
            return C(id="ollama", label=label, status="warn", detail="Ollama is not running.", fix_hint=hint)
        if not any(n == want or n.split(":")[0] == want for n in models):
            return C(id="ollama", label=label, status="warn",
                     detail=f"Ollama is running but {want} is not pulled.", fix_hint=hint)  # fmt: skip
        return C(id="ollama", label=label, status="pass", detail=f"Running with {want}.")

    # 11 ----------------------------------------------------------------------------------
    def disk(self) -> m.PreflightCheck:
        free = self.p.free_disk_bytes(self.root)
        label = "Free disk space"
        detail = f"{_gb(free)} free."
        if free < DISK_FAIL_BYTES:
            return C(id="disk", label=label, status="fail", detail=detail,
                     fix_hint="Free disk space; at least 5 GB is recommended.")  # fmt: skip
        if free < DISK_WARN_BYTES:
            return C(id="disk", label=label, status="warn", detail=detail,
                     fix_hint="Free at least 5 GB.")  # fmt: skip
        return C(id="disk", label=label, status="pass", detail=detail)


_ORDER: tuple[str, ...] = (
    "camera", "broker", "broker_port", "supabase", "cloud_usage", "gemini_keys", "nvidia_key",
    "mapbox_token", "depth_model", "ollama", "disk",
)  # fmt: skip


def collect_preflight(
    settings: Settings, probes: Probes, now: datetime | None = None
) -> tuple[m.PreflightReport, Facts]:
    """Run every check in parallel; return the report (I3 order) and the measured facts."""
    runner = _Runner(settings, probes)
    fns: list[Callable[[], m.PreflightCheck]] = [getattr(runner, cid) for cid in _ORDER]

    def guarded(cid: str, fn: Callable[[], m.PreflightCheck]) -> m.PreflightCheck:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001  (never include the message: it may carry a key)
            log.warning("preflight check %s failed: %s", cid, type(exc).__name__)
            return C(id=cid, label=cid, status="fail",  # type: ignore[arg-type]
                     detail=f"The check failed unexpectedly ({type(exc).__name__}).",
                     fix_hint="Run preflight again; if it persists, check the Ground Station log.")  # fmt: skip

    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(guarded, cid, fn) for cid, fn in zip(_ORDER, fns, strict=True)]
        checks = [f.result() for f in futures]
    ran_at = to_iso(now or datetime.now(UTC))
    return m.PreflightReport(ran_at=ran_at, checks=checks), runner.facts


def run_preflight(settings: Settings, probes: Probes, now: datetime | None = None) -> m.PreflightReport:
    return collect_preflight(settings, probes, now)[0]
