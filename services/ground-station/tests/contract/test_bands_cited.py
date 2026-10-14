"""Task 8: every stressor band carries a citation and a source URL (addendum N1)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
PARAMS = ["do_mg_l", "ph", "turbidity_ntu", "salinity_psu", "porewater_salinity_psu", "temp_c"]


def test_every_band_has_citation():
    bands = yaml.safe_load((ROOT / "config" / "bands.yaml").read_text(encoding="utf-8"))
    for p in PARAMS:
        entry = bands["parameters"][p]
        assert entry["citation"] and entry["citation"].strip(), p
        assert entry["source_url"].startswith("https://"), p


def test_bands_load_through_settings_model():
    from bcs_gs.core.config import Bands

    raw = yaml.safe_load((ROOT / "config" / "bands.yaml").read_text(encoding="utf-8"))
    b = Bands.model_validate(raw)
    assert all(b.parameters[p].citation for p in PARAMS)
