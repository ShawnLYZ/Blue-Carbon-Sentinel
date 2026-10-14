import math
import re
from pathlib import Path

import pytest
from bcs_gs.core.config import load_settings
from bcs_gs.site.registry import SiteRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def haversine(a, b):
    """Haversine distance in metres between two (lng, lat) points.

    A sphere is 0.1-0.7 % off the WGS84 ellipsoid at this latitude (about 0.5 m over 500 m),
    so the sphere radius is replaced by the local WGS84 radius of curvature along the bearing:
    the prime-vertical radius N for due east and the meridian radius M for due north.
    """
    (lng1, lat1), (lng2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    pm = (p1 + p2) / 2
    a_, e2 = 6378137.0, 0.00669437999014
    w = math.sqrt(1 - e2 * math.sin(pm) ** 2)
    n_rad, m_rad = a_ / w, a_ * (1 - e2) / w**3
    # weight by the share of the displacement along each axis
    de, dn = abs(dl) * math.cos(pm) * n_rad, abs(dp) * m_rad
    r = (de * n_rad + dn * m_rad) / (de + dn) if de + dn else n_rad
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@pytest.fixture
def reg():
    return SiteRegistry(load_settings(REPO_ROOT, env_file=None).site)


def test_zone_ids_cover_a1_to_e5_west_east_north_south(reg):
    ids = [z.id for z in reg.zones()]
    assert len(ids) == 25 and ids[0] == "KSL-A1" and ids[-1] == "KSL-E5"
    assert reg.zone_at(e=150, s=250) == "KSL-B3"


def test_raster_metres_lnglat_round_trip(reg):
    for u, v in [(0, 0), (511.5, 0.5), (256, 256)]:
        e, s = reg.raster_to_metres(u, v)
        lng, lat = reg.metres_to_lnglat(e, s)
        e2, s2 = reg.lnglat_to_metres(lng, lat)
        assert abs(e - e2) < 0.01 and abs(s - s2) < 0.01
    assert reg.raster_to_metres(512, 512) == (500.0, 500.0)


def test_coordinate_id_format(reg):
    z = reg.zone("KSL-B3")
    assert re.fullmatch(r"KSL-N\d\.\d{4}-E\d{3}\.\d{4}", z.coordinate_id)


def test_zone_polygon_ring_is_nw_ne_se_sw_closed(reg):
    ring = reg.zone("KSL-A1").bounds["coordinates"][0]
    assert ring[0] == ring[-1] and ring[1][0] > ring[0][0] and ring[2][1] < ring[1][1]


def test_square_is_500m_on_both_axes(reg):
    nw = reg.metres_to_lnglat(0, 0)
    ne = reg.metres_to_lnglat(500, 0)
    sw = reg.metres_to_lnglat(0, 500)
    assert abs(haversine(nw, ne) - 500) < 0.5 and abs(haversine(nw, sw) - 500) < 0.5
