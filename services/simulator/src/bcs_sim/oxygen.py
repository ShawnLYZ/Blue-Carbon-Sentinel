"""Dissolved-oxygen saturation (Garcia & Gordon 1992, Benson & Krause fit)."""

from __future__ import annotations

import math

_A = (2.00907, 3.22014, 4.05010, 4.94457, -0.256847, 3.88767)
_B = (-6.24523e-3, -7.37614e-3, -1.03410e-2, -8.17083e-3)
_C0 = -4.88682e-7
_MG_PER_ML = 1.42905


def do_saturation_mg_l(temp_c: float, salinity_psu: float) -> float:
    ts = math.log((298.15 - temp_c) / (273.15 + temp_c))
    s = salinity_psu
    ln_c = (
        sum(a * ts**i for i, a in enumerate(_A)) + s * sum(b * ts**i for i, b in enumerate(_B)) + _C0 * s * s
    )
    return math.exp(ln_c) * _MG_PER_ML
