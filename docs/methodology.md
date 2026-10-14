# Methodology

How Blue Carbon Sentinel turns pixels and sensor readings into a risk score. Code measures; AI only
interprets (multipliers in [0.5, 1.5] and a narrative). Every number below lives in `config/`.

## 1. NDVI-proxy: VARI on top-down RGB

The camera is a plain RGB camera, so there is no near-infrared band and no true NDVI. The vegetation
index is VARI (Visible Atmospherically Resistant Index):

    VARI = (G - R) / (G + R - B)

computed per pixel on the rectified 512 x 512 site raster and clamped to [-1, 1]. It is stored as a
16-bit map (`ndvi.png`, [-1, 1] mapped to 0-65535). Healthy canopy has a high green share, so VARI is
high; dying canopy shifts towards yellow-brown and VARI falls.

Image bands: the camera raster has bands `("R","G","B")`. A Sentinel-2 source (swap guide) has `("B2","B3","B4","B8")` and
allows true NDVI = (B8 - B4) / (B8 + B4) (Rouse et al. 1974; ESA Sentinel-2 band definitions). VARI after Gitelson et al.
(2002), Remote Sensing of Environment 80:76-87 (https://doi.org/10.1016/S0034-4257(01)00289-9).

Limits, stated in the UI as "NDVI proxy" (the NDVI-proxy): VARI is not calibrated to NDVI; it reacts to lighting and white
balance (hence the exposure lock in the camera confidence), and it cannot see sub-canopy stress. Values
are compared against the zone's own baseline, never against absolute NDVI thresholds. The vegetation
stressor (N2) is `clamp(max(canopy_loss_pp / 30, dieback_pct / 50, vari_drop / 0.30), 0, 1)` and is
unmeasured until a baseline exists.

## 2. Parameter bands and citations

Each sensor parameter becomes a stressor in [0, 1] by a piecewise-linear breakpoint table (`config/bands.yaml`,
addendum N1). Convention: 0 at the edge of "Good", 0.6 where "Critical" starts, 1.0 at saturation; values are
held constant beyond the end points.

Status after Task 8: `cited_partial`. No breakpoint moved from the N1 defaults. The sources found confirm or
bracket the defaults and nowhere clearly contradict them, so there was no case for changing them. How far
each source backs each table (`evidence` in the YAML):

| Parameter | Breakpoints (value -> stress) | Evidence | What the source states |
|---|---|---|---|
| DO (mg/L) | 0.5 -> 1, 2 -> 0.6, 5 -> 0 | direct | MWQCS (DOE Malaysia) dissolved oxygen: Class 1 >80% saturation, Class 2 5, Class 3 3, Class E (mangroves, estuarine, river-mouth) 4 mg/L. The Good edge is the Class 2 value; Class E sits on the ramp at stress 0.2. The 2 mg/L Critical start is judgement (conventional hypoxia level). |
| pH | 6 -> 1, 6.5 -> 0.6, 7 -> 0, 8.5 -> 0, 9 -> 0.6, 9.5 -> 1 | judgement | The MWQCS table has no pH row. The Interim National Water Quality Standards (freshwater) give 6-9 for Class IIA/IIB. N1 default kept as judgement. **Gap: no marine pH criterion found.** |
| Turbidity (NTU) | 25 -> 0, 100 -> 0.6, 300 -> 1 | context | The MWQCS has no turbidity row; **TSS is the proxy**: Class 1 25, Class 2 50, Class 3 100, Class E 100 mg/L (or at most +30% on the seasonal average). Assuming 1 NTU is about 1 mg/L TSS (site-specific; needs local calibration), 25 and 100 NTU match Class 1 and the Class E limit. |
| Salinity (PSU) | 35 -> 0, 45 -> 0.6, 60 -> 1 | context | Sobrado 1999 (A. germinans, 0-40 permil): maximum photosynthesis -21% at 10 and -37% at 40 permil. Guo et al. 2023 (A. marina): benefit up to 200 mM NaCl, decline above 400 mM. Hypersaline is defined as above 40 (Dittmann et al. 2022). Seawater (35) as the Good edge, 45 and 60 provisional. |
| Porewater salinity (PSU) | 40 -> 0, 60 -> 0.6, 90 -> 1 | direct | Dittmann et al. 2022 (A. marina): healthy 35-43, stressed 37-66, dieback mean 98.5 (84-109); mortality cited above 74, 80 and 93; canopy loss at 68.5. Watzka and Medina 2018: Rhizophora is the more salt-sensitive genus (photosynthesis -36% vs -21% in Avicennia at hypersaline sites). |
| Temperature (degC) | 32 -> 0, 36 -> 0.6, 40 -> 1 | judgement | The MWQCS allows at most +2 degC over maximum ambient (relative only). Andrews and Muller 1985 (R. stylosa): photosynthesis inhibited progressively as leaf temperature rises (abstract read; no absolute threshold taken). Absolute points are N1 judgement. |

Species caveat: salinity tolerance differs by genus (Avicennia tolerates more than Rhizophora). One band set is used for the whole site, so Rhizophora plots may stress earlier than the stressor shows; the RiskInterpreter multipliers are the place for that nuance, not the bands.

Sources (all read in full or in the abstract/page shown; none quoted from memory):
- DOE Malaysia, Malaysia Marine Water Quality Criteria and Standard (copy: https://environment.com.my/wp-content/uploads/2016/05/Marine.pdf).
- DOE Malaysia, Interim National Water Quality Standards (https://wepa-db.net/archive/policies/law/malaysia/eq_surface.htm).
- Dittmann et al. (2022), Front. For. Glob. Change 5:859283 (https://doi.org/10.3389/ffgc.2022.859283).
- Watzka and Medina (2018), IntechOpen chapter "Mangroves in Contrasting Osmotic Environments" (https://www.intechopen.com/chapters/59769).
- Sobrado (1999), Photosynthetica 36(4):547-555 (https://doi.org/10.1023/A:1007092004582).
- Guo et al. (2023), Tree Physiology 43(5):817 (https://academic.oup.com/treephys/article/43/5/817/6972260).
- Andrews and Muller (1985), Oecologia 65:449-455 (https://doi.org/10.1007/BF00378922).

Changes from the N1 defaults: none. Open items: a marine pH criterion, a turbidity-to-TSS calibration for
the site, and an absolute temperature limit are still to be sourced; swap them into `bands.yaml`
(and the fusion test values) if found.

## 3. Risk (N3)

Base weights: vegetation 0.35, salinity 0.10, porewater 0.15, turbidity 0.15, DO 0.15, temperature 0.05, pH 0.05.
The RiskInterpreter may scale each weight by a multiplier in [0.5, 1.5] (rules tier: 1.0). Unmeasured stressors
are dropped and the remaining weights renormalised to sum to 1. Risk = 100 x sum(w'_i x s_i). Class, from the
unrounded score: low < 30, medium < 60, high < 80, critical >= 80. With no measured stressor there is no
assessment ("no data"). Early warning: vegetation < 0.2 while the sensor composite >= 0.5, sustained for
3 investigation samples or 2 baseline samples.

## 4. Confidence (N4)

Camera confidence = q x r x l x k: capture quality (1.0 evidence-grade, else 0.6); recency (1.0 up to 60 s,
0.5 at 600 s, 0.3 from 1,800 s; at most 0.5 with the camera offline); exposure lock (1.0, else 0.85);
calibration (1.0 four-corner, 0.9 default); 0.1 with no capture. Sensor confidence = max(0.1, f x phi x eta x psi):
share of sensor weight measured (over 0.65), freshness (within 3 intervals), online and battery (>= 15%),
and a 0.8 penalty for an active stuck or spike flag. Prediction confidence is the answering tier's factor:
Gemini primary 0.95, secondary 0.90, local Gemma 0.80, rules 0.75.

## 5. Carbon constants and quantities (M6)

Status: cited (the "provisional" label is gone). Methodology wording: aligned with Verra VM0033 (Tidal Wetland and
Seagrass Restoration) concepts — demo, not certified. Every record and page is a "Demo record — not a certified carbon
credit". All constants live in `config/carbon.yaml` as `{value, unit, citation, source_url}`.

| Constant | Value | Source | Cross-check / caveat |
|---|---|---|---|
| Ecosystem density | 1,074 Mg C/ha | Donato et al. 2011, Nature Geoscience 4:293-297 (https://doi.org/10.1038/ngeo1123): estuarine mean 1,074 (+/-171 s.e.m.); oceanic 990; all sites 1,023; soil is 71-98% of the estuarine total | IPCC 2013 Wetlands Supplement Tier 1 (Tables 4.3, 4.5, 4.11): about 87 Mg C/ha above ground (192 t d.m. x 0.451) plus roots plus 1 m soil (mineral 286, organic 471) is roughly 415-600 Mg C/ha. Lower because Tier 1 stops at 1 m of soil. The Donato figure is for estuarine sites; whether KSL is estuarine was not established. |
| Biomass density | 159 Mg C/ha | Donato 2011: above-ground carbon pools, mean 159 (max 435), all 25 sites (the M5 placeholder was 160) | IPCC Table 4.3 x 4.2: tropical wet 192 t d.m./ha x 0.451 = 86.6 Mg C/ha. Donato's mean is about twice IPCC's region-wide mean (mature Indo-Pacific stands vs all ages). |
| CO2e per C | 44/12 = 3.6667 | Molar-mass ratio (CO2 44.009, C 12.011; PubChem https://pubchem.ncbi.nlm.nih.gov/compound/Carbon-dioxide) | The IPCC chapter text does not state 44/12, so it is not cited for it. |
| Cohort rate, age 5-9 | 4.0 Mg C/ha/yr | Kairo et al. 2008, For. Ecol. Manage. 255:2670-2677 (https://doi.org/10.1016/j.foreco.2008.01.031): 12-year Rhizophora mucronata plantation, 106.7 t d.m./ha = 8.9 t d.m./ha/yr; x 0.451 (IPCC Table 4.2) = 4.0 | IPCC Table 4.4 tropical wet growth 9.9 t d.m./ha/yr = 4.5 Mg C/ha/yr. Above ground only; a 12-year average, not a 5-9 year measurement. |
| Cohort rate, age 0-4 | 2.0 Mg C/ha/yr | **Not confirmed by a source.** Engineering judgement (half the older band) | Kairo et al. 2009 (Aquatic Conservation; DOI 10.1002/aqc.1046 was reported by a search and not opened): 5- and 8-year plantations averaged 20.25 t d.m./ha, about 1.4 Mg C/ha/yr as a cumulative average (ages behind the mean not confirmed). To be replaced if a young-stand rate is found. |
| Buffer | 15 % | Verra AFOLU Non-Permanence Risk Tool v4.1, 29 Aug 2023 (https://verra.org/documents/afolu-non-permanence-risk-tool-v4-1): buffer % = overall risk rating, minimum 12 % (2.5.3), above 60 % the project fails (2.5.4) | 15 % is a demo choice above the 12 % floor. The "10-20 %" range in the brief was not found in the tool and is not relied on. |

Not confirmed: the age 0-4 rate above; that the Donato estuarine mean suits the site; the Kairo 2009 DOI. The
uncertainty deduction parameters (offset 0.10, cap 0.5) are the product's own rule (spec section 22), not sourced.

**Stock versus additionality (ruling R6).** The two numbers on the Time Travel page differ by about 100x on purpose:

- *Carbon stock (standing)* is the carbon held by the whole ecosystem, soil included: canopy fraction x area x
  1,074 Mg C/ha x 44/12, about 3,900 tCO2e per hectare at full canopy.
- *Additional* is only what the plan adds from 2026 to 2035: the cohort sequestration (a flux of 2-4 Mg C/ha/yr,
  about 7-15 tCO2e/ha/yr, scaled by planted area and survival) plus the avoided *biomass* loss (with minus without,
  at 159 Mg C/ha). Avoided soil carbon is never credited, which is also why the stock cannot be read as credit.

They are never added or compared as like with like; the UI labels them "standing" and "extra sequestration since
2026, not part of the stock". No scaling factor connects them.

**Deductions.** Net = gross - buffer - uncertainty, where buffer = gross x 15 % and uncertainty = (gross - buffer) x
clamp((1 - overall confidence) - 0.10, 0, 0.5). tCO2e are `Decimal`, 3 dp, rounded half-even, each component rounded
independently and the net rounded from the unrounded sum.

## 6. Forecast (design section 19)

Yearly keyframes 2026 to 2035 for two scenarios (with and without the applied plan), run three times (low, central, high
parameter sets) to give bands. State per zone: canopy fraction C, health H, land fraction L and stress sigma, taken from the
latest evidence-grade capture and the risk components. Annual dynamics, a pure function of the inputs:

    canopy:  dC = g * C * (1 - C / L) * (1 - sigma) - m * sigma * C        g in [0, 0.15], m in [0, 0.40] per year
    health:  H moves to 1 at h_rec * (1 - sigma) and to 0 at h_dec * sigma    both in [0, 0.5]
    erosion: dL = -e * (1 - C)                                              e in [0, 0.05] (0.05 is about 5 m/yr over 100 m)
    stress:  without the plan sigma follows a trend in [-0.05, +0.10] per year; with it, intervention effects scale stressors

Intervention effects (stress multipliers, adjustable by the AI within +/-50 %): silt fence turbidity x 0.4; reopen channel
porewater salinity and DO x 0.5; stop pollution DO and pH x 0.3. Planted cohorts: 4,400 saplings/ha, survival in [0.3, 0.9]
by species, logistic canopy growth with time constants of 5-7 years (Rhizophora) and 4-6 (Avicennia), capped at land L.

Status: the bounds, rules-tier defaults and effects in `config/forecast.yaml` are marked PROVISIONAL engineering
values; they are bounded and validated, but not calibrated to field data. No source is claimed for them. The
ForecastParameterEstimator (AI) returns central values with low/high ranges and a justification, validated against the
bounds; the rules tier supplies the defaults. A cached-parameter run is expected to complete within 1 s.

## 7. Classification and zone metrics (addendum N11, tuned on the tank in M7)

Classes with precedence canopy > water > mud > other (OpenCV HSV scales): canopy = ExG above the Otsu threshold of the
baseline (0.05 before a baseline exists) and S > 40; water = (V < 70 and S < 60) or (H 85-130 and S > 40), with local
texture (7 x 7 Laplacian variance) < 40; mud = (H 5-30, S 30-160, V 40-200) or (S < 30, V 70-200). Dieback is the share of
baseline canopy pixels whose hue is now 10-35 or whose VARI fell below the zone baseline p10 - 0.05; new growth is canopy
outside the dilated baseline mask in components of 4-400 px, as a % of zone area. A capture is evidence-grade when
sharpness >= 60, mean brightness is 40-220, clipped pixels <= 5 %, there is no motion and exposure is locked. These
thresholds are provisional; changes found on the tank are recorded below.

## 8. Ledger rules and constants (design section 23, addendum N8 and N13)

- **Record:** ID `BC-{year}-{5-digit sequence}`; type Projected or Verified; quantity with its gross and deductions
  breakdown; site, zones, crediting period (2026-2035); evidence references (captures, telemetry window with a
  `simulated` flag, forecast run, plan and version, AI calls with tier and model); confidence components; the label
  "Demo record - not a certified carbon credit"; previous hash and hash.
- **Hash chain:** SHA-256 over canonical JSON (sorted keys, separators `,` and `:`, UTF-8, non-integers as fixed-place
  decimal strings: tCO2e 3 dp, fractions and confidences 4 dp, percentages 2 dp). Genesis: index 0, previous hash 64 zeros.
  Verifying re-parses the canonical text, checks it re-serialises byte-identically, recomputes the hash and checks the
  link and index continuity; the first failing index is reported. The database rejects UPDATE and DELETE by trigger and
  only the Ground Station inserts; indices are allocated locally so the chain stays valid offline.
- **Projected record:** from an applied plan's forecast; needs the checklist Satellite, Sensor, AI, Restoration.
  Quantity = additionality minus deductions (section 5), aligned with Verra VM0033 concepts.
- **Verified record**, issued automatically when, for the planted zones of an applied plan: (1) at least 3 consecutive
  evidence-grade captures after application show recovery (new growth >= 3 % of zone area, or canopy +5 percentage
  points against the capture at application); (2) covering sensors keep every stressor < 0.3 continuously for the demo-time
  window (120 s; 86,400 s with demo time off), with at least one water-quality or soil node covering; (3) overall
  confidence >= 0.80; (4) full chain verification passes. Quantity = the Projected quantity for those zones x the
  verification ratio (observed recovery over expected first-milestone recovery, capped at 1.0), rounded to 3 dp.
- **Constants:** every carbon constant, with citation and URL, is in section 5 and `config/carbon.yaml`: Donato et al.
  (2011) densities, 44/12, Kairo et al. (2008) cohort rates and the 15 % buffer above the Verra non-permanence floor.

## 9. Tank tuning log

Filled in during the tank session (M7 Task 7): one row per threshold changed, with the measured values that justified it.

| Date | Parameter (file) | Old | New | Evidence |
|---|---|---|---|---|
