"""Capture API shapes (addendum I3) and the capture events (J2) built from stored rows."""

from __future__ import annotations

from typing import Any

from bcs_gs.api.models import Capture, CaptureMediaUrls, CaptureQuality, CaptureSummary, ZoneMetrics
from bcs_gs.capture.artefacts import FILES
from bcs_gs.vegetation import ZoneMetricsRow

MEDIA_URL = "/api/v1/media/captures/{id}/{kind}"


def to_capture(row: dict[str, Any], metrics: list[Any]) -> Capture:
    urls = {kind: MEDIA_URL.format(id=row["id"], kind=kind) for kind in FILES}
    return Capture(
        id=row["id"], taken_at=row["taken_at"], trigger=row["trigger"], evidence_grade=row["evidence_grade"],
        is_baseline=row["is_baseline"], flagged=row["flagged"], change_score=row["change_score"],
        quality=CaptureQuality.model_validate(row["quality"]), thumb_url=urls["image"],
        calibration_id=row["calibration_id"], imagery_source=row["imagery_source"], bands=list(row["bands"]),
        media_urls=CaptureMediaUrls(**urls), media_state=row["media_state"],
        zone_metrics=[ZoneMetrics.model_validate(m.model_dump(exclude={"capture_id"})) for m in metrics],
    )  # fmt: skip


def capture_events(
    capture: Capture, metrics: dict[str, ZoneMetricsRow], baseline: bool
) -> list[tuple[str, dict[str, Any]]]:
    summary = CaptureSummary.model_validate(capture.model_dump(include=set(CaptureSummary.model_fields)))
    out: list[tuple[str, dict[str, Any]]] = [
        ("capture.created", summary.model_dump(mode="json")),
        (
            "zone.metrics",
            {
                "capture_id": capture.id,
                "metrics": [m.model_dump(mode="json", exclude={"capture_id"}) for m in metrics.values()],
            },
        ),
    ]
    for z, m in metrics.items():
        if m.flags:
            out.append(
                (
                    "zone.flagged",
                    {
                        "zone_id": z,
                        "capture_id": capture.id,
                        "flags": [f.model_dump(mode="json") for f in m.flags],
                    },
                )
            )
    if baseline:
        out.append(("baseline.updated", {"capture_id": capture.id}))
    return out
