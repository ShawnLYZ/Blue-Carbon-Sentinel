"""M6 Task 1: every carbon constant carries a value, unit, citation and https source URL (R1)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
KEYS = ["ecosystem_density_mg_c_ha", "biomass_density_mg_c_ha", "co2e_per_c", "cohort_rates", "buffer_pct"]


def _load():
    return yaml.safe_load((ROOT / "config" / "carbon.yaml").read_text(encoding="utf-8"))


def test_every_carbon_constant_is_cited():
    c = _load()
    for k in KEYS:
        assert c[k]["citation"].strip() and c[k]["source_url"].startswith("https://"), k
        assert c[k]["unit"] and "value" in c[k], k


def test_buffer_is_percent_and_not_provisional():
    c = _load()
    assert c["buffer_pct"]["value"] == 15 and c["buffer_pct"]["unit"] == "%"
    assert "status" not in c and "provisional" not in yaml.safe_dump(c).lower()


def test_cohort_rates_are_age_bands():
    bands = _load()["cohort_rates"]["value"]
    assert bands[0]["min_age"] == 0 and all({"min_age", "max_age", "rate"} <= set(b) for b in bands)


def test_co2e_per_c_is_44_over_12_and_matches_core():
    from bcs_gs.carbon.core import C_TO_CO2E

    assert abs(_load()["co2e_per_c"]["value"] - 44 / 12) < 1e-9 and abs(C_TO_CO2E - 44 / 12) < 1e-12


def test_carbon_loads_through_settings_model():
    from bcs_gs.core.config import load_settings

    c = load_settings(ROOT, env_file=None).carbon
    assert c.buffer_pct.value == 15 and c.ecosystem_density_mg_c_ha.value == 1074
