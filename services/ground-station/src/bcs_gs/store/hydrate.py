"""Hydration (addendum H6, M7): a machine with an empty local store pulls its state from the Cloud Store.

Pulled: the last 24 h of telemetry and alerts; sites, zones, calibrations, devices, commissioning runs;
plans, forecasts, ledger records, evidence packs; the latest history generation; the baseline and the
referenced captures (with their metrics and media). Rows are written with ``sync=False`` so nothing is
echoed back into the outbox; the ledger chain is verified afterwards.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso

from bcs_gs.core.clock import Clock
from bcs_gs.ledger.contents import parse_canonical
from bcs_gs.store.cloud import SELECT_PAGE_MAX, CloudError, CloudTarget, Filter
from bcs_gs.store.media import MediaStore
from bcs_gs.store.repo import Repo
from bcs_gs.store.retention import evidence_capture_ids
from bcs_gs.store.schema import SYNCED_TABLES

log = logging.getLogger("bcs_gs.hydrate")

WINDOW = timedelta(hours=24)
ID_CHUNK = 100  # ids per "in" filter
# A store holding any row of these has history: hydration is for a fresh machine only (startup seeds
# the site and the camera device, so those tables do not count).
HISTORY_TABLES = (
    "telemetry", "ledger_records", "restoration_plans", "forecasts", "captures", "commissioning_runs",
)  # fmt: skip


@dataclass
class HydrationReport:
    tables: dict[str, int] = field(default_factory=dict)  # rows written per table
    media: int = 0  # media objects downloaded
    media_skipped: int = 0  # pruned, or not fetchable
    chain_intact: bool | None = None  # None: no ledger records
    chain_checked: int = 0


def select_all(
    cloud: CloudTarget, table: str, filters: list[Filter] | None = None, order: list[str] | None = None
) -> list[dict[str, Any]]:
    """Every matching row, ``SELECT_PAGE_MAX`` (1,000) at a time. The primary key always ends the sort,
    so rows tied on the requested order keep one position across pages."""
    sort = [*(order or []), *(c for c in SYNCED_TABLES[table].pk if c not in {o.lstrip("-") for o in order or []})]
    out: list[dict[str, Any]] = []
    while True:
        page = cloud.select(table, filters, sort, SELECT_PAGE_MAX, len(out))
        out.extend(page)
        if len(page) < SELECT_PAGE_MAX:
            return out


def select_in(cloud: CloudTarget, table: str, column: str, values: set[str]) -> list[dict[str, Any]]:
    ids = sorted(values)
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), ID_CHUNK):
        out.extend(select_all(cloud, table, [(column, "in", ids[i : i + ID_CHUNK])]))
    return out


MARKER_KEY = "hydration"


def needs_hydration(repo: Repo) -> bool:
    """True on a fresh store, or when an earlier hydration started and did not finish (its marker says
    so): a crash midway leaves history rows behind, which must not pass for a complete store."""
    marker = repo.get("settings", {"key": MARKER_KEY})
    if marker is not None and marker["value"].get("state") != "complete":
        return True
    return not any(repo.query(f'SELECT 1 FROM "{t}" LIMIT 1') for t in HISTORY_TABLES)


def _mark(repo: Repo, clock: Clock, state: str) -> None:
    repo.upsert(
        "settings",
        {"key": MARKER_KEY, "value": {"state": state}, "updated_at": to_iso(clock.now())},
        sync=False,
    )


def _normalise(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """A cloud row as the local store holds it: only known columns, timestamps in the store's format
    (Postgres returns ``+00:00`` and microseconds)."""
    spec = SYNCED_TABLES[table]
    out: dict[str, Any] = {}
    for col, typ in spec.columns.items():
        if col not in row:
            continue
        val = row[col]
        if val is not None and typ == "timestamp" and isinstance(val, str):
            val = to_iso(from_iso(val))
        out[col] = val
    if table == "ledger_records":
        _restore_ledger_text(out)
    return out


def _restore_ledger_text(row: dict[str, Any]) -> None:
    """Postgres returns ``numeric(14,3)`` as a JSON number (1.25 for "1.250"). The chain check compares
    these text columns with the canonical text, so the number is formatted to the column's scale. It is
    never read from the canonical: a cloud display column that differs from it must verify as broken."""
    for col in ("quantity_tco2e", "gross_tco2e"):
        if col in row and row[col] is not None and not isinstance(row[col], str):
            row[col] = f"{Decimal(str(row[col])):.3f}"


class _Writer:
    def __init__(self, repo: Repo, report: HydrationReport) -> None:
        self.repo, self.report = repo, report

    def write(self, table: str, rows: list[dict[str, Any]]) -> None:
        spec = SYNCED_TABLES[table]
        n = 0
        with self.repo.transaction():
            for raw in rows:
                row = _normalise(table, raw)
                if spec.sync_op == "insert_ignore":  # insert-only tables: a present row stays as it is
                    if self.repo.get(table, {c: row[c] for c in spec.pk}) is not None:
                        continue
                    self.repo.insert(table, row, sync=False)
                else:
                    self.repo.upsert(table, row, sync=False)
                n += 1
        self.report.tables[table] = self.report.tables.get(table, 0) + n


def _single_active_calibration(repo: Repo, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most one calibration is active (a unique index): the cloud's newest active one replaces a
    locally seeded one, and any older active row the cloud still holds is written inactive."""
    active = sorted((r for r in rows if r.get("active")), key=lambda r: r["created_at"])
    if not active:
        return rows
    keep = active[-1]["id"]
    for r in repo.query("SELECT * FROM calibrations WHERE active = 1", table="calibrations"):
        if r["id"] != keep:
            repo.upsert("calibrations", {**r, "active": False}, sync=False)
    return [{**r, "active": r["id"] == keep} if r.get("active") else r for r in rows]


def hydrate(repo: Repo, media: MediaStore, cloud: CloudTarget, clock: Clock) -> HydrationReport:
    """Blocking. Raises ``CloudError`` when the cloud cannot be read; media that cannot be fetched is
    skipped and counted. Repeating it is safe: present rows are overwritten (insert-only ones kept)."""
    report = HydrationReport()
    _mark(repo, clock, "incomplete")
    w = _Writer(repo, report)
    since = to_iso(clock.now() - WINDOW)

    for t in ("sites", "zones", "calibrations", "devices", "device_history"):
        rows = select_all(cloud, t)
        if t == "calibrations":
            rows = _single_active_calibration(repo, rows)
        w.write(t, rows)
    runs = select_all(cloud, "commissioning_runs")
    w.write("commissioning_runs", runs)
    plans = select_all(cloud, "restoration_plans", order=["created_at"])
    forecasts = select_all(cloud, "forecasts", order=["created_at"])
    ledger = select_all(cloud, "ledger_records", order=["chain_index"])
    packs = select_all(cloud, "evidence_packs", order=["generated_at"])

    wanted = {r["id"] for r in select_all(cloud, "captures", [("is_baseline", "eq", True)])}
    wanted |= {r["capture_id"] for r in runs if r.get("capture_id")}
    wanted |= {f["base_capture_id"] for f in forecasts if f.get("base_capture_id")}
    wanted |= {p["capture_at_application_id"] for p in plans if p.get("capture_at_application_id")}
    for rec in ledger:  # from the hashed canonical content, never the display column (M6 ruling)
        content = parse_canonical(rec.get("canonical")) or {}
        wanted |= evidence_capture_ids(content.get("evidence"))
    captures = select_in(cloud, "captures", "id", wanted)
    w.write("captures", captures)
    w.write("zone_metrics", select_in(cloud, "zone_metrics", "capture_id", {c["id"] for c in captures}))

    w.write("restoration_plans", plans)
    w.write("forecasts", forecasts)
    w.write("ledger_records", ledger)
    w.write("evidence_packs", packs)

    latest = cloud.select("history_series", None, ["-created_at", "-id"], 1)
    if latest:
        gen = latest[0]["generation_id"]
        w.write("history_series", select_all(cloud, "history_series", [("generation_id", "eq", gen)]))

    w.write("telemetry", select_all(cloud, "telemetry", [("sampled_at", "gte", since)], ["sampled_at"]))
    w.write("alerts", select_all(cloud, "alerts", [("at", "gte", since)], ["at"]))

    for cap in captures:
        if cap.get("media_state") == "pruned":
            report.media_skipped += 1
            continue
        for key in sorted(set((cap.get("media") or {}).values())):
            _fetch(media, cloud, report, "captures", key)
    for pack in packs:
        _fetch(media, cloud, report, "evidence-packs", pack["media_key"])

    _mark(repo, clock, "complete")
    _verify_chain(repo, clock, report)
    state = {True: "intact", False: "BROKEN", None: "empty"}[report.chain_intact]
    log.info(
        "hydrated %d rows, %d media objects (%d skipped); ledger chain %s",
        sum(report.tables.values()), report.media, report.media_skipped, state,
    )  # fmt: skip
    return report


def _fetch(media: MediaStore, cloud: CloudTarget, report: HydrationReport, bucket: str, key: str) -> None:
    try:
        present = media.path(bucket, key).is_file()
    except ValueError as exc:  # a key the local store refuses (e.g. escapes the media root): skip it
        report.media_skipped += 1
        log.warning("media %s/%r not restored: %s", bucket, key, exc)
        return
    if present:
        return
    try:
        data = cloud.download(bucket, key)
    except CloudError as exc:
        report.media_skipped += 1
        log.warning("media %s/%s not restored: %s", bucket, key, exc)
        return
    ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
    media.put(bucket, key, data, ctype, cloud=False)
    with media.db.tx() as conn:  # it came from the cloud: nothing to upload
        conn.execute("UPDATE media_objects SET state = 'uploaded' WHERE bucket = ? AND key = ?", (bucket, key))
    report.media += 1


def _verify_chain(repo: Repo, clock: Clock, report: HydrationReport) -> None:
    from bcs_gs.ledger.chain import verify
    from bcs_gs.ledger.service import VERIFY_SQL, _stored

    rows = repo.query(VERIFY_SQL)
    if not rows:
        return
    v = verify([_stored(r) for r in rows], at=to_iso(clock.now()))
    report.chain_intact, report.chain_checked = v.intact, v.checked
    if not v.intact:
        log.error("hydrated ledger chain is BROKEN at index %s", v.first_broken_index)
