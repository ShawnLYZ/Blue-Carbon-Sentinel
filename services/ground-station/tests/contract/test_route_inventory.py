"""Every addendum I2 route is declared; unbuilt routes answer 501 with their milestone."""

import re
from pathlib import Path

from bcs_gs.api.app import Overrides, create_app
from bcs_gs.core.config import load_settings

REPO_ROOT = Path(__file__).resolve().parents[4]

# Addendum I2, verbatim: (method, path, milestone). Combined rows are expanded one route each.
I2 = [
    ("GET", "/api/v1/system/status", "M1"),
    ("GET", "/api/v1/system/preflight", "M1"),
    ("POST", "/api/v1/system/preflight", "M1"),
    ("GET", "/api/v1/system/config", "M1"),
    ("GET", "/api/v1/system/settings", "M1"),
    ("PATCH", "/api/v1/system/settings", "M1"),
    ("GET", "/api/v1/camera/status", "M2"),
    ("PATCH", "/api/v1/camera/settings", "M2"),
    ("POST", "/api/v1/camera/lock", "M2"),
    ("POST", "/api/v1/camera/reconnect", "M2"),
    ("GET", "/api/v1/calibration", "M2"),
    ("GET", "/api/v1/calibration/frame.jpg", "M2"),
    ("POST", "/api/v1/calibration/four-corner", "M2"),
    ("POST", "/api/v1/calibration/reset", "M2"),
    ("POST", "/api/v1/baseline", "M2"),
    ("GET", "/api/v1/site", "M1"),
    ("GET", "/api/v1/zones", "M1"),
    ("GET", "/api/v1/zones/{zone_id}", "M2"),
    ("GET", "/api/v1/captures", "M2"),
    ("GET", "/api/v1/captures/latest", "M2"),
    ("GET", "/api/v1/captures/{capture_id}", "M2"),
    ("POST", "/api/v1/captures", "M2"),
    ("GET", "/api/v1/captures/compare", "M2"),
    ("GET", "/api/v1/media/captures/{capture_id}/{kind}", "M2"),
    ("GET", "/api/v1/media/compare/{a}/{b}/change.png", "M2"),
    ("GET", "/api/v1/media/live/latest.jpg", "M2"),
    ("GET", "/api/v1/media/futures/{forecast_id}/{scenario}/{year}/{kind}", "M5"),
    ("GET", "/api/v1/media/illustrations/{illustration_id}.jpg", "M5"),
    ("GET", "/api/v1/trees", "M4"),
    ("POST", "/api/v1/trees/locate", "M4"),
    ("GET", "/api/v1/nodes", "M3"),
    ("GET", "/api/v1/nodes/{node_id}", "M3"),
    ("GET", "/api/v1/nodes/{node_id}/telemetry", "M3"),
    ("GET", "/api/v1/nodes/{node_id}/events", "M3"),
    ("POST", "/api/v1/nodes", "M3"),
    ("POST", "/api/v1/nodes/{node_id}/move", "M3"),
    ("POST", "/api/v1/nodes/{node_id}/decommission", "M3"),
    ("POST", "/api/v1/nodes/{node_id}/regenerate-key", "M3"),
    ("GET", "/api/v1/commissioning", "M3"),
    ("POST", "/api/v1/commissioning", "M3"),
    ("GET", "/api/v1/coverage", "M3"),
    ("GET", "/api/v1/tasks", "M3"),
    ("POST", "/api/v1/tasks", "M3"),
    ("POST", "/api/v1/tasks/{task_id}/cancel", "M3"),
    ("POST", "/api/v1/tasks/{task_id}/release", "M3"),
    ("GET", "/api/v1/zones/{zone_id}/assessments", "M4"),
    ("POST", "/api/v1/zones/{zone_id}/analyze", "M4"),
    ("GET", "/api/v1/history", "M4"),
    ("POST", "/api/v1/history/regenerate", "M4"),
    ("GET", "/api/v1/ai/status", "M4"),
    ("GET", "/api/v1/ai/calls", "M4"),
    ("GET", "/api/v1/ai/calls/export", "M4"),
    ("POST", "/api/v1/plans/propose", "M5"),
    ("GET", "/api/v1/plans", "M5"),
    ("GET", "/api/v1/plans/{plan_id}", "M5"),
    ("PUT", "/api/v1/plans/{plan_id}", "M5"),
    ("POST", "/api/v1/plans/{plan_id}/apply", "M5"),
    ("POST", "/api/v1/forecasts", "M5"),
    ("GET", "/api/v1/forecasts/latest", "M5"),
    ("GET", "/api/v1/forecasts/{forecast_id}", "M5"),
    ("GET", "/api/v1/forecasts/{forecast_id}/illustrations", "M5"),
    ("GET", "/api/v1/carbon/summary", "M6"),
    ("GET", "/api/v1/ledger/records", "M6"),
    ("GET", "/api/v1/ledger/records/{record_id}", "M6"),
    ("GET", "/api/v1/ledger/checklist", "M6"),
    ("POST", "/api/v1/ledger/projected", "M6"),
    ("GET", "/api/v1/ledger/eligibility", "M6"),
    ("POST", "/api/v1/ledger/verify", "M6"),
    ("GET", "/api/v1/ledger/records/{record_id}/evidence-pack", "M6"),
    ("GET", "/api/v1/alerts", "M4"),
    ("POST", "/api/v1/alerts/{alert_id}/ack", "M4"),
    ("GET", "/api/v1/director", "M7"),
    ("POST", "/api/v1/director/start", "M7"),
    ("POST", "/api/v1/director/skip", "M7"),
    ("POST", "/api/v1/director/retry", "M7"),
    ("POST", "/api/v1/director/stop", "M7"),
]
I2_ROUTES = [(m, p) for m, p, _ in I2]
BUILT = {"M1", "M2", "M3", "M7"}  # milestones whose routes are implemented
# Routes of a milestone in progress that are already built.
BUILT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/v1/zones/{zone_id}/assessments"),  # M4 Task 5
    ("POST", "/api/v1/zones/{zone_id}/analyze"),  # M4 Task 5
    ("GET", "/api/v1/alerts"),  # M4 Task 6
    ("POST", "/api/v1/alerts/{alert_id}/ack"),  # M4 Task 6
    ("GET", "/api/v1/history"),  # M4 Task 7
    ("POST", "/api/v1/history/regenerate"),  # M4 Task 7
    ("GET", "/api/v1/trees"),  # M4 Task 7
    ("POST", "/api/v1/trees/locate"),  # M4 Task 7
    ("GET", "/api/v1/ai/status"),  # M4 Task 7
    ("GET", "/api/v1/ai/calls"),  # M4 Task 7
    ("GET", "/api/v1/ai/calls/export"),  # M4 Task 7
    ("POST", "/api/v1/forecasts"),  # M5 Task 3 (ruling R8)
    ("GET", "/api/v1/forecasts/latest"),  # M5 Task 3
    ("GET", "/api/v1/forecasts/{forecast_id}"),  # M5 Task 3
    ("POST", "/api/v1/plans/propose"),  # M5 Task 4 (ruling R8)
    ("GET", "/api/v1/plans"),  # M5 Task 4
    ("GET", "/api/v1/plans/{plan_id}"),  # M5 Task 4
    ("PUT", "/api/v1/plans/{plan_id}"),  # M5 Task 4
    ("POST", "/api/v1/plans/{plan_id}/apply"),  # M5 Task 4
    ("GET", "/api/v1/media/futures/{forecast_id}/{scenario}/{year}/{kind}"),  # M5 Task 5 (ruling R8)
    ("GET", "/api/v1/forecasts/{forecast_id}/illustrations"),  # M5 Task 7
    ("GET", "/api/v1/media/illustrations/{illustration_id}.jpg"),  # M5 Task 7
    ("GET", "/api/v1/carbon/summary"),  # M6 Task 6
    ("GET", "/api/v1/ledger/records"),  # M6 Task 3 (ruling R2)
    ("GET", "/api/v1/ledger/records/{record_id}"),  # M6 Task 3
    ("GET", "/api/v1/ledger/checklist"),  # M6 Task 3
    ("POST", "/api/v1/ledger/projected"),  # M6 Task 3
    ("POST", "/api/v1/ledger/verify"),  # M6 Task 3
    ("GET", "/api/v1/ledger/eligibility"),  # M6 Task 4
    ("GET", "/api/v1/ledger/records/{record_id}/evidence-pack"),  # M6 Task 5
}


def _built(r: tuple[str, str, str]) -> bool:
    return r[2] in BUILT or (r[0], r[1]) in BUILT_ROUTES


def make_settings():
    return load_settings(REPO_ROOT, env_file=None)


def test_every_addendum_route_is_declared():
    paths = {
        (m.upper(), p) for p, item in create_app(make_settings()).openapi()["paths"].items() for m in item
    }
    assert [r for r in I2_ROUTES if r not in paths] == []


def test_test_routes_absent_outside_test_mode():
    app = create_app(make_settings(), overrides=Overrides(test_mode=False))
    assert "/api/v1/test/reset" not in app.openapi()["paths"]


def test_test_routes_present_in_test_mode():
    app = create_app(make_settings(), overrides=Overrides(test_mode=True))
    paths = app.openapi()["paths"]
    for p in (
        "/api/v1/test/reset",
        "/api/v1/test/clock/advance",
        "/api/v1/test/clock/set",
        "/api/v1/test/cloud/fail",
        "/api/v1/test/seed/capture",
    ):
        assert p in paths


async def test_every_unbuilt_route_is_501_with_its_milestone(gs):
    bad = []
    for method, path, milestone in (r for r in I2 if not _built(r)):
        url = re.sub(r"\{(\w+)\}", lambda m: "2030" if m.group(1) == "year" else "x", path)
        r = await gs.http.request(method, url)
        err = r.json().get("error", {}) if r.status_code == 501 else {}
        if err.get("code") != "not_implemented" or err.get("details") != {"milestone": milestone}:
            bad.append((method, path, r.status_code))
    assert bad == []


async def test_no_built_route_answers_501(gs):
    bad = []
    for method, path, _ in (r for r in I2 if _built(r)):
        url = re.sub(r"\{(\w+)\}", lambda m: "2030" if m.group(1) == "year" else "x", path)
        if (await gs.http.request(method, url)).status_code == 501:
            bad.append((method, path))
    assert bad == []


def test_openapi_publishes_i3_model_names_and_no_model_suffix_leaks():
    schemas = create_app(make_settings()).openapi()["components"]["schemas"]
    for name in ("Site", "Zone", "PlannedSite", "SystemStatus", "PublicConfig", "PreflightReport",
                 "ErrorEnvelope", "Settings", "ZoneSummary", "ZoneDetail", "CameraStatus", "Calibration",
                 "Capture", "CaptureSummary", "CaptureComparison", "ZoneMetrics"):  # fmt: skip
        assert name in schemas, name
    assert [n for n in schemas if n.endswith("Model")] == []
