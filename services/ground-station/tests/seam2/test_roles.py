"""Task 3: the four AI roles, their bounds checks, rules tiers and prompt files."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from bcs_gs.ai.roles import PROMPTS
from bcs_gs.ai.roles._common import RoleConfig, default_role_config
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.ai.roles.history_synthesizer import (
    HistoryInput,
    HistoryOutput,
    HistoryPoint,
    HistorySynthesizer,
)
from bcs_gs.ai.roles.risk_interpreter import (
    RiskInput,
    RiskInterpreter,
    RiskOutput,
    RootCauseOut,
)
from bcs_gs.ai.roles.tree_locator import TreeInput, TreeLocator, TreeOutput, TreePoint
from bcs_gs.ai.roles.vision_analyst import (
    VisionAnalyst,
    VisionInput,
    VisionObservation,
    VisionOutput,
)
from bcs_gs.api.models import ZoneFlag, ZoneMetrics
from bcs_gs.vegetation.trees import blob_centroids

CFG = default_role_config()


def m(zone_id="KSL-B3", **kw) -> ZoneMetrics:
    base = {
        "zone_id": zone_id, "canopy_pct": 50.0, "water_pct": 20.0, "mud_pct": 20.0, "other_pct": 10.0,
        "dieback_pct": 0.0, "new_growth_pct": 0.0,
    }  # fmt: skip
    return ZoneMetrics(**{**base, **kw})


def vin(**kw) -> VisionInput:
    base = {
        "zone_ids": ["KSL-B3"], "current_jpeg": b"cur", "previous_jpeg": b"prev",
        "metrics": {"KSL-B3": m(canopy_pct=38.0)},
    }  # fmt: skip
    return VisionInput(**{**base, **kw})


def vout(narrative="Canopy thinned in B3", observations=None) -> VisionOutput:
    obs = observations or [
        VisionObservation(zone_id="KSL-B3", kind="dieback", confidence=0.8, text="Browning")
    ]
    return VisionOutput(observations=obs, narrative=narrative)


def tin(classes=None) -> TreeInput:
    return TreeInput(raster_jpeg=b"jpeg", classes=classes)


def hin(seed=1, zones=None) -> HistoryInput:
    zones = zones or {
        "KSL-B3": {"canopy_pct": 38.0, "vari_mean": 0.12},
        "KSL-A1": {"canopy_pct": 70.0, "vari_mean": 0.3},
    }
    return HistoryInput(zones=zones, site_context="25 ha Kuala Selangor mangrove", seed=seed)


STRESSORS = {
    "vegetation": 0.6, "salinity": 0.2, "porewater_salinity": 0.5, "turbidity": 0.4,
    "do": 0.1, "temperature": 0.0, "ph": 0.05,
}  # fmt: skip
READINGS = {
    "salinity": 36.0, "porewater_salinity": 55.0, "turbidity": 80.0,
    "do": 4.5, "temperature": 30.0, "ph": 7.4,
}  # fmt: skip
INP = RiskInput(
    zone_id="KSL-B3", stressors=STRESSORS, metrics=m(canopy_loss_pp=12.0),
    readings_summary=READINGS, context="",
)  # fmt: skip
INP_WITHOUT_PH = RiskInput(
    zone_id="KSL-B3",
    stressors={k: v for k, v in STRESSORS.items() if k != "ph"},
    metrics=m(),
    readings_summary={k: v for k, v in READINGS.items() if k != "ph"},
    context="",
)


def out(**kw) -> RiskOutput:
    base = {
        "multipliers": {},
        "root_causes": [RootCauseOut(driver="vegetation", rank=1, why="canopy loss")],
        "narrative": "n",
        "actions": ["a"],
    }
    return RiskOutput(**{**base, **kw})


def test_risk_multiplier_out_of_bounds_rejected():
    with pytest.raises(OutputRejected):
        RiskInterpreter().check(out(multipliers={"turbidity": 3.0}), INP)
    with pytest.raises(OutputRejected):
        RiskInterpreter().check(out(multipliers={"ph": 1.0}), INP_WITHOUT_PH)
    RiskInterpreter().check(out(multipliers={"turbidity": 1.2}), INP)


def test_vision_output_cannot_carry_numbers_that_override_code():
    with pytest.raises(OutputRejected):
        VisionAnalyst().check(
            vout(narrative="Canopy is now 65% in B3"), vin(metrics={"KSL-B3": m(canopy_pct=38.0)})
        )
    VisionAnalyst().check(
        vout(narrative="Canopy in B3 dropped to 38.0%"), vin(metrics={"KSL-B3": m(canopy_pct=38.0)})
    )
    VisionAnalyst().check(vout(narrative="Canopy in B3 dropped to 38%, tile 2025"), vin())


def test_vision_text_decimal_and_zone_checks():
    with pytest.raises(OutputRejected):
        VisionAnalyst().check(vout(narrative="VARI fell by 0.45"), vin())
    bad_obs = [VisionObservation(zone_id="KSL-B3", kind="none", confidence=0.5, text="up 12.5 pp")]
    with pytest.raises(OutputRejected):
        VisionAnalyst().check(vout(observations=bad_obs), vin())
    foreign = [VisionObservation(zone_id="KSL-Z9", kind="none", confidence=0.5, text="ok")]
    with pytest.raises(OutputRejected):
        VisionAnalyst().check(vout(observations=foreign), vin())


def test_vision_rules_use_only_input_numbers():
    flag = ZoneFlag(kind="canopy_loss", value=12.0, threshold=10.0)
    inp = vin(metrics={"KSL-B3": m(canopy_pct=38.0, canopy_loss_pp=12.0, dieback_pct=7.5, flags=[flag])})
    res = VisionAnalyst().rules(inp)
    assert [o.zone_id for o in res.observations] == ["KSL-B3"]
    assert res.observations[0].kind == "dieback"
    assert "38" in res.narrative
    VisionAnalyst().check(res, inp)


def test_tree_rules_are_blob_centroids_in_normalised_coords():
    classes = np.zeros((512, 512), np.uint8)
    classes[100:120, 200:220] = 1
    pts = TreeLocator().rules(tin(classes=classes)).points
    assert len(pts) == 1 and pts[0].y == pytest.approx(214, abs=3) and pts[0].x == pytest.approx(410, abs=3)


def test_tree_rules_without_classes_and_small_blobs():
    assert TreeLocator().rules(tin(classes=None)).points == []
    classes = np.zeros((64, 64), np.uint8)
    classes[1:4, 1:4] = 1
    assert blob_centroids(classes, min_area_px=30) == []


def test_tree_check_range_and_count():
    TreeLocator().check(TreeOutput(points=[TreePoint(y=10, x=20, label="tree")]), tin())
    bad = TreeOutput.model_construct(points=[TreePoint.model_construct(y=1200, x=5, label="t")])
    with pytest.raises(OutputRejected):
        TreeLocator().check(bad, tin())


def test_history_rules_end_at_current_measured_value_and_are_seeded():
    a = HistorySynthesizer().rules(hin(seed=1))
    b = HistorySynthesizer().rules(hin(seed=1))
    assert a == b and a.series["KSL-B3"][-1].year == 2025
    assert a.series["KSL-B3"][-1].canopy_pct == pytest.approx(
        hin(seed=1).zones["KSL-B3"]["canopy_pct"], abs=0.5
    )
    assert HistorySynthesizer().rules(hin(seed=2)) != a
    HistorySynthesizer().check(a, hin(seed=1))


def test_history_check_rejects_short_series_and_far_end():
    pts = [HistoryPoint(year=y, canopy_pct=38.0, vari_equiv=0.1) for y in range(2016, 2026)]
    inp = hin(zones={"KSL-B3": {"canopy_pct": 38.0, "vari_mean": 0.1}})
    HistorySynthesizer().check(HistoryOutput(series={"KSL-B3": pts}), inp)
    with pytest.raises(OutputRejected):
        HistorySynthesizer().check(HistoryOutput(series={"KSL-B3": pts[1:]}), inp)
    far = [*pts[:-1], HistoryPoint(year=2025, canopy_pct=60.0, vari_equiv=0.1)]
    with pytest.raises(OutputRejected):
        HistorySynthesizer().check(HistoryOutput(series={"KSL-B3": far}), inp)


def test_risk_rules_neutral_ranked_and_robust_without_reading():
    res = RiskInterpreter().rules(INP)
    assert all(v == 1.0 for v in res.multipliers.values())
    assert res.root_causes[0].driver == "vegetation" and res.root_causes[0].rank == 1
    assert res.narrative.startswith("Main driver: vegetation (")
    assert len(res.actions) <= 5
    RiskInterpreter().check(res, INP)
    no_veg = RiskInput(
        zone_id="Z", stressors={"vegetation": 0.9}, metrics=None, readings_summary={}, context=""
    )
    assert RiskInterpreter().rules(no_veg).narrative.startswith("Main driver: vegetation")


def test_requests_carry_schema_and_vision_images_are_downscaled():
    big = cv2.imencode(".jpg", np.zeros((2000, 3000, 3), np.uint8))[1].tobytes()
    req = VisionAnalyst().request(vin(current_jpeg=big, previous_jpeg=big))
    imgs = [p for p in req.parts if isinstance(p, bytes)]
    assert len(imgs) == 2 and req.timeout_s == CFG.vision_timeout_s and req.temperature == CFG.temperature
    for b in imgs:
        h, w = cv2.imdecode(np.frombuffer(b, np.uint8), 1).shape[:2]
        assert max(h, w) <= CFG.max_image_px
    assert req.response_schema["type"] == "object" and "$defs" not in req.response_schema
    assert RiskInterpreter().request(INP).timeout_s == CFG.text_timeout_s
    assert HistorySynthesizer().request(hin()).timeout_s == CFG.text_timeout_s
    assert TreeLocator().request(tin()).timeout_s == CFG.vision_timeout_s


def test_prompts_are_versioned_files():
    for r in [VisionAnalyst(), TreeLocator(), RiskInterpreter(), HistorySynthesizer()]:
        assert (PROMPTS / f"{r.name}.{r.prompt_version}.md").exists()
        assert r.schema_version == "1" and r.prompt_version == "v1"


def test_config_comes_from_the_committed_yaml():
    import yaml

    root = PROMPTS.parents[5]
    ai = yaml.safe_load((root / "config" / "ai.yaml").read_text(encoding="utf-8"))
    risk = yaml.safe_load((root / "config" / "risk.yaml").read_text(encoding="utf-8"))
    assert CFG.temperature == ai["temperature"] and CFG.max_image_px == ai["image"]["max_px"]
    assert (
        CFG.text_timeout_s == ai["timeouts_s"]["text"] and CFG.vision_timeout_s == ai["timeouts_s"]["vision"]
    )
    assert CFG.weights == risk["weights"] and CFG.multiplier_bounds == tuple(risk["multiplier_bounds"])
    assert CFG.units["do"] == "mg/L" and CFG.units["ph"] == "pH"
    custom = RoleConfig(**{**CFG.__dict__, "temperature": 0.7, "multiplier_bounds": (0.8, 1.2)})
    assert VisionAnalyst(custom).request(vin()).temperature == 0.7
    with pytest.raises(OutputRejected):
        RiskInterpreter(custom).check(out(multipliers={"turbidity": 1.4}), INP)


def test_risk_text_numbers_must_come_from_inputs():
    ri = RiskInterpreter()
    with pytest.raises(OutputRejected):
        ri.check(out(narrative="Canopy is 65% in B3"), INP)
    with pytest.raises(OutputRejected):
        ri.check(out(root_causes=[RootCauseOut(driver="vegetation", rank=1, why="loss of 33.3 pp")]), INP)
    with pytest.raises(OutputRejected):
        ri.check(out(actions=["Cut salinity to 12.5 PSU"]), INP)
    ri.check(out(narrative="Porewater salinity is 55.0 PSU and turbidity 80 NTU; canopy loss 12.0 pp"), INP)
