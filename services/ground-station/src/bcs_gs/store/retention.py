"""Cloud media budget (addendum A2) and local capture / futures thinning (addendum H7)."""

from __future__ import annotations

import shutil
from datetime import timedelta
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.core.clock import Clock
from bcs_gs.ledger.contents import stored_contents
from bcs_gs.store.cloud import CloudTarget
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.repo import Repo

DEFAULT_BUDGET_BYTES = 800_000_000
KEEP_FORECASTS = 3


def _capture_id(key: str) -> str:
    """Captures keys are ``yyyy/mm/dd/<capture_id>/<file>``."""
    parts = key.split("/")
    return parts[3] if len(parts) >= 5 else ""


def evidence_capture_ids(evidence: Any) -> set[str]:
    """The capture IDs a ledger record's evidence references (``evidence.captures[].id``), matched
    exactly: an ID that merely appears inside another string is not a reference (H7)."""
    caps = evidence.get("captures") if isinstance(evidence, dict) else None
    if not isinstance(caps, list):
        return set()
    return {c["id"] for c in caps if isinstance(c, dict) and isinstance(c.get("id"), str)}


def latest_ready_forecasts(repo: Repo) -> set[str]:
    """The forecasts whose futures media is kept: the latest three *ready* ones (ruling R30 #7)."""
    return {
        r["id"]
        for r in repo.query(
            "SELECT id FROM forecasts WHERE status = 'ready' ORDER BY created_at DESC, id DESC LIMIT ?",
            (KEEP_FORECASTS,),
        )
    }


class MediaBudget:
    def __init__(self, db: Database, cloud: CloudTarget, budget_bytes: int = DEFAULT_BUDGET_BYTES) -> None:
        self.db = db
        self.cloud = cloud
        self.budget_bytes = budget_bytes
        self._repo = Repo(db)

    def _uploaded(self) -> list[dict]:
        return self._repo.query(
            "SELECT bucket, key, bytes, protected, uploaded_at FROM media_objects WHERE state = 'uploaded'"
            " ORDER BY uploaded_at, key",
            table="media_objects",
        )

    def _mark_pruned(self, objs: list[dict]) -> None:
        with self.db.tx() as conn:
            conn.executemany(
                "UPDATE media_objects SET state = 'pruned' WHERE bucket = ? AND key = ?",
                [(o["bucket"], o["key"]) for o in objs],
            )

    def enforce(self) -> list[tuple[str, str]]:
        objs = self._uploaded()
        total = sum(o["bytes"] for o in objs)
        pruned: list[tuple[str, str]] = []
        if total <= self.budget_bytes:
            return pruned

        # 1. unprotected capture media, oldest capture first, whole capture at a time
        groups: dict[str, list[dict]] = {}
        for o in objs:
            if o["bucket"] == "captures" and not o["protected"]:
                groups.setdefault(_capture_id(o["key"]), []).append(o)
        for cap_id, group in sorted(groups.items(), key=lambda kv: (kv[1][0]["uploaded_at"] or "", kv[0])):
            if total <= self.budget_bytes:
                return pruned
            self.cloud.remove("captures", [o["key"] for o in group])
            self._mark_pruned(group)
            row = self._repo.get("captures", {"id": cap_id}) if cap_id else None
            if row is not None and row["media_state"] != "pruned":
                self._repo.upsert("captures", {**row, "media_state": "pruned"})
            total -= sum(o["bytes"] for o in group)
            pruned.extend((o["bucket"], o["key"]) for o in group)

        # 2. futures media of forecast runs older than the latest three ready ones (pending and failed runs
        #    have no futures media and must not push a ready run's media out of the protected three)
        latest = latest_ready_forecasts(self._repo)
        for o in objs:
            if total <= self.budget_bytes:
                break
            if o["bucket"] != "futures" or o["protected"] or o["key"].split("/")[0] in latest:
                continue
            self.cloud.remove("futures", [o["key"]])
            self._mark_pruned([o])
            total -= o["bytes"]
            pruned.append((o["bucket"], o["key"]))
        return pruned


class Retention:
    def __init__(self, db: Database, media: MediaStore, clock: Clock) -> None:
        self.db = db
        self.media = media
        self.clock = clock
        self._repo = Repo(db)

    def _protected_ids(self) -> set[str]:
        q = self._repo.query
        ids = {r["id"] for r in q("SELECT id FROM captures WHERE is_baseline = 1")}
        for sql in (
            "SELECT capture_at_application_id AS c FROM restoration_plans",
            "SELECT base_capture_id AS c FROM forecasts",
            "SELECT capture_id AS c FROM commissioning_runs",
            "SELECT capture_id AS c FROM tree_points",
        ):
            ids |= {r["c"] for r in q(sql) if r["c"]}
        ids |= {r["id"] for r in q("SELECT id FROM captures WHERE retention_reason = 'ledger_evidence'")}
        for _, content in stored_contents(self._repo):  # the hashed canonical content, not the display column
            ids |= evidence_capture_ids(content.get("evidence"))
        return ids

    def thin_captures(self) -> int:
        cutoff = to_iso(self.clock.now() - timedelta(hours=24))
        old = self._repo.query(
            "SELECT id, taken_at FROM captures WHERE taken_at < ? ORDER BY taken_at, id", (cutoff,)
        )
        protected = self._protected_ids()
        seen: set[str] = set()
        doomed: list[str] = []
        for r in old:
            minute = r["taken_at"][:16]
            first = minute not in seen
            seen.add(minute)
            if not first and r["id"] not in protected:
                doomed.append(r["id"])
        files: list[tuple[str, str]] = []
        thinned: list[str] = []
        with self.db.tx() as conn:
            for cap_id in doomed:
                objs = conn.execute(
                    "SELECT key, state FROM media_objects WHERE bucket = 'captures' AND key LIKE ?",
                    (f"%/{cap_id}/%",),
                ).fetchall()
                if any(o["state"] == "pending" for o in objs):
                    continue  # eligible media not uploaded yet: thin it on a later run
                thinned.append(cap_id)
                conn.execute("DELETE FROM zone_metrics WHERE capture_id = ?", (cap_id,))
                conn.execute("DELETE FROM captures WHERE id = ?", (cap_id,))
                files.extend(("captures", o["key"]) for o in objs)
                # Uploaded rows stay: the cloud copy still exists and counts against the budget.
                conn.execute(
                    "DELETE FROM media_objects WHERE bucket = 'captures' AND key LIKE ? AND state != 'uploaded'",
                    (f"%/{cap_id}/%",),
                )
        for bucket, key in files:
            try:
                self.media.path(bucket, key).unlink(missing_ok=True)
            except (ValueError, OSError):
                continue
        return len(thinned)

    def thin_futures(self) -> int:
        """Delete, locally only, the futures media of every forecast outside the latest three ready ones
        (a forecast whose row is gone included). The cloud copy is never touched here; the budget prunes
        it. A forecast with a protected file is kept whole. Returns the number of forecasts thinned."""
        root = self.media.path("futures", "x").parent  # var/media/futures
        if not root.is_dir():
            return 0
        keep = latest_ready_forecasts(self._repo)
        protected = {
            r["key"].split("/")[0]
            for r in self._repo.query(
                "SELECT key FROM media_objects WHERE bucket = 'futures' AND protected = 1",
                table="media_objects",
            )
        }
        doomed = [d.name for d in sorted(root.iterdir()) if d.is_dir() and d.name not in keep | protected]
        for fid in doomed:
            shutil.rmtree(root / fid, ignore_errors=True)
        if doomed:
            with self.db.tx() as conn:
                for fid in doomed:  # uploaded rows stay: the cloud copy still exists and counts in the budget
                    conn.execute(
                        "DELETE FROM media_objects WHERE bucket = 'futures' AND key LIKE ? AND state != 'uploaded'",
                        (f"{fid}/%",),
                    )
        return len(doomed)
