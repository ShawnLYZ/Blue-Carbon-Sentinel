"""M5 Task 4: the restoration catalogue constraints (pure)."""

from __future__ import annotations

import pytest
from bcs_gs.api.errors import ApiError
from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem
from bcs_gs.restoration.catalogue import ZonePlanState, is_eroded, validate_items


def plant(zone: str, kind: str, saplings: int, *extra: str) -> PlanItem:
    ivs = [Intervention(kind=kind, sapling_count=saplings), *(Intervention(kind=k) for k in extra)]
    return PlanItem(
        zone_id=zone,
        interventions=ivs,
        priority=1,
        rationale="test",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0.0, tco2e_2035=0.0),
    )


def state(mud: float = 0.2, porewater: float | None = None, eroded: bool = False) -> ZonePlanState:
    return ZonePlanState(mud=mud, porewater_psu=porewater, eroded=eroded)


def test_planting_requires_mud_or_eroded_edge():  # Review Focus 2
    with pytest.raises(ApiError) as e:
        validate_items([plant("KSL-A1", "plant_rhizophora", 1000)], {"KSL-A1": state(mud=0.0, eroded=False)})
    assert "planting needs mud or an eroded edge in KSL-A1" in e.value.message
    assert e.value.status == 422 and e.value.code == "validation_error"


def test_species_suitability_warns_above_40_psu():  # Review Focus 2
    items, warnings = validate_items(
        [plant("KSL-B3", "plant_rhizophora", 880)], {"KSL-B3": state(mud=0.2, porewater=46)}
    )
    assert items[0].interventions[0].kind == "plant_avicennia" and warnings == [
        "switched to Avicennia marina: porewater > 40 PSU"
    ]
    assert items[0].interventions[0].planted_area_ha == pytest.approx(0.2)


def test_eroded_edge_allows_planting_without_mud():
    items, warnings = validate_items(
        [plant("KSL-A1", "plant_avicennia", 440)], {"KSL-A1": state(mud=0.0, eroded=True)}
    )
    assert items[0].interventions[0].planted_area_ha == pytest.approx(0.1) and warnings == []


def test_mud_threshold_is_two_percent_and_unknown_zone_has_no_mud():
    validate_items([plant("KSL-A1", "plant_rhizophora", 10)], {"KSL-A1": state(mud=0.02)})
    with pytest.raises(ApiError):
        validate_items([plant("KSL-A1", "plant_rhizophora", 10)], {"KSL-A1": state(mud=0.019)})
    with pytest.raises(ApiError):
        validate_items([plant("KSL-A1", "plant_rhizophora", 10)], {})


def test_non_planting_items_need_no_mud_and_keep_given_area():
    item = plant("KSL-A1", "plant_rhizophora", 100, "silt_fence")
    item.interventions[0].planted_area_ha = 0.5
    items, _ = validate_items([item], {"KSL-A1": state(mud=0.1, porewater=40)})  # 40 is not above 40
    assert [iv.kind for iv in items[0].interventions] == ["plant_rhizophora", "silt_fence"]
    assert items[0].interventions[0].planted_area_ha == 0.5
    only_fence = plant("KSL-A1", "plant_rhizophora", 0, "reopen_channel")
    only_fence.interventions.pop(0)
    validate_items([only_fence], {"KSL-A1": state(mud=0.0)})


def test_drop_mode_removes_invalid_planting_with_a_warning():
    items, warnings = validate_items(
        [plant("KSL-A1", "plant_rhizophora", 1000, "silt_fence"), plant("KSL-A2", "plant_rhizophora", 10)],
        {"KSL-A1": state(mud=0.0), "KSL-A2": state(mud=0.0)},
        drop_invalid=True,
    )
    assert [(i.zone_id, [iv.kind for iv in i.interventions]) for i in items] == [("KSL-A1", ["silt_fence"])]
    assert warnings == [
        "dropped plant_rhizophora in KSL-A1: planting needs mud or an eroded edge in KSL-A1",
        "dropped plant_rhizophora in KSL-A2: planting needs mud or an eroded edge in KSL-A2",
    ]


def test_eroded_edge_rule():
    assert is_eroded(water=0.05, mud=0.01, land_without=None)  # water >= 5 % next to mud
    assert not is_eroded(water=0.05, mud=0.0, land_without=None)
    assert not is_eroded(water=0.04, mud=0.01, land_without=[0.9, 0.89])
    assert is_eroded(water=0.0, mud=0.0, land_without=[0.9, 0.89, 0.88])  # L falls 0.02 by 2035
    assert not is_eroded(water=0.0, mud=0.0, land_without=[0.9, 0.885])


# ---- ruling R30 (#8): at most 1 ha planted per zone -----------------------------------------------------
def test_planted_area_per_zone_is_capped_at_one_hectare():
    ok = [plant("KSL-B3", "plant_rhizophora", 2200), plant("KSL-B3", "plant_avicennia", 2200)]
    items, _ = validate_items(ok, {"KSL-B3": state()})  # 0.5 + 0.5 ha: exactly 1 ha is allowed
    assert sum(iv.planted_area_ha for it in items for iv in it.interventions) == pytest.approx(1.0)
    over = [plant("KSL-B3", "plant_rhizophora", 2200), plant("KSL-B3", "plant_avicennia", 2201)]
    with pytest.raises(ApiError) as e:
        validate_items(over, {"KSL-B3": state()})
    assert e.value.status == 422 and e.value.code == "validation_error"
    assert e.value.message == "planted area exceeds 1 ha in KSL-B3"


def test_planted_area_cap_sums_interventions_within_one_item_and_given_areas():
    item = plant("KSL-B3", "plant_rhizophora", 100)
    item.interventions[0].planted_area_ha = 0.7
    item.interventions.append(Intervention(kind="plant_avicennia", planted_area_ha=0.4))
    with pytest.raises(ApiError, match="planted area exceeds 1 ha in KSL-B3"):
        validate_items([item], {"KSL-B3": state()})
    # other zones have their own hectare
    items, _ = validate_items(
        [plant("KSL-B3", "plant_rhizophora", 4400), plant("KSL-C3", "plant_rhizophora", 4400)],
        {"KSL-B3": state(), "KSL-C3": state()},
    )
    assert len(items) == 2


def test_ai_draft_drops_planting_over_one_hectare_with_a_warning():  # consistent with ruling R19
    first = plant("KSL-B3", "plant_rhizophora", 3520, "silt_fence")  # 0.8 ha
    second = plant("KSL-B3", "plant_avicennia", 1320)  # 0.3 ha: would make 1.1 ha
    items, warnings = validate_items([first, second], {"KSL-B3": state()}, drop_invalid=True)
    assert [iv.kind for it in items for iv in it.interventions] == ["plant_rhizophora", "silt_fence"]
    assert warnings == ["dropped plant_avicennia in KSL-B3: planted area exceeds 1 ha in KSL-B3"]


def planted(zone: str, saplings: int | None, area: float | None) -> PlanItem:
    iv = Intervention(kind="plant_rhizophora", sapling_count=saplings, planted_area_ha=area)
    return PlanItem(
        zone_id=zone, interventions=[iv], priority=1, rationale="test",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0.0, tco2e_2035=0.0),
    )  # fmt: skip


def test_sapling_density_above_4400_per_ha_is_rejected_on_operator_edits():  # M5 follow-up
    items, _ = validate_items([planted("KSL-B3", 2200, 0.5)], {"KSL-B3": state()})  # exactly 4,400/ha is fine
    assert items[0].interventions[0].planted_area_ha == 0.5
    for n, area in ((2201, 0.5), (-1, 0.5), (10, -0.5)):
        with pytest.raises(ApiError) as e:
            validate_items([planted("KSL-B3", n, area)], {"KSL-B3": state()})
        assert e.value.status == 422 and e.value.code == "validation_error"
        assert e.value.message == "sapling density exceeds 4400 per ha in KSL-B3"


def test_ai_draft_drops_planting_over_density_with_a_warning():
    items, warnings = validate_items([planted("KSL-B3", 3000, 0.5)], {"KSL-B3": state()}, drop_invalid=True)
    assert items == [] and warnings == [
        "dropped plant_rhizophora in KSL-B3: sapling density exceeds 4400 per ha in KSL-B3"
    ]
