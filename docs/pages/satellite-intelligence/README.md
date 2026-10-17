# Satellite Intelligence

[All page guides](../README.md)

**Routes:** `?mangrove-preview#/satellite` (open imagery preview), `#/satellite` (original camera workflow). **Keyboard shortcut:** `2`.

## Purpose and business value

Inspect the location and observation quality behind a project assessment. Farm owners, buyers and investors can view the site, check when imagery was acquired, and distinguish observations from modelling assumptions.

## Open satellite preview

| Feature | What the user can do |
|---|---|
| Location | Enter WGS84 latitude/longitude and select **Explore site** |
| Study footprint | Inspect a fixed 500 × 500 m area (25 ha) |
| Acquisition selector | Choose an available Sentinel-2 L2A scene |
| True colour / Vegetation · NDVI | Switch between observed colour and a masked vegetation index |
| Check latest imagery | Refresh the catalogue; visible pages also check periodically |
| Natural forest / Restoration farm | Compare procedural forest appearance and planted restoration rows |
| Environment settings | Adjust salinity, inundation, stand age and spacing assumptions |
| Observation quality | Review usable clear land, mean land NDVI and vegetated study area |

The default site is Kuala Selangor Nature Park. Imagery is read from open Earth Search catalogue assets and cloud-optimised GeoTIFFs. Satellite observation state is shared with the preview Digital Twin and Carbon Ledger during the app session.

## How to use it

1. Open the preview route and wait for a scene to load.
2. Check the acquisition date and the usable clear-land percentage.
3. Switch to NDVI to inspect vegetation signals; select an earlier scene if clouds obscure the site.
4. Compare Natural forest and Restoration farm appearances.
5. Adjust environment settings as a scenario, then use **Reset assumptions** when finished.
6. Open the Digital Twin to inspect risk attributes for the same observation.

**Explore an illustrative footprint instead** permits appearance experiments without treating the footprint as observed vegetation.

## Original camera workflow

Without `?mangrove-preview`, this route presents SentinelCam live view, four-corner calibration, baseline controls, capture history, a before/after slider, observations, history charts and per-zone metrics. It requires Ground Station services and camera/capture data. Camera imagery and its vegetation proxy are separate from the open Sentinel-2 observation.

## Data and limitations

- “Latest” means latest available satellite acquisitions, not continuous or real-time video.
- NDVI is calculated from scaled red and near-infrared reflectance. Scene classes exclude cloud, shadow, water and other unsuitable pixels from the clear-land index.
- Trees are placed on clear land with NDVI ≥ 0.35. Vegetation is not classified specifically as mangrove.
- The 10 m display cannot resolve individual trees, tree heights or roots. Tree instances and environment effects are procedural estimates, not a field inventory or calibrated forecast.
- Salinity, age, inundation and spacing controls are manual assumptions, not satellite measurements.
- The open preview needs internet access and browser graphics support; its imagery does not require a Mapbox token. The original map-based workflow does.

## Troubleshooting

**No imagery:** check network access to the catalogue and raster assets, retry, or select another acquisition. **Grey/obscured NDVI:** inspect cloud and usable-land indicators before drawing conclusions. **3D unavailable:** the page can retain imagery and controls while displaying its graphics fallback.

## Relevant implementation files

- [MangrovePreview.tsx](../../../apps/mission-control/src/preview/MangrovePreview.tsx)
- [satellite.ts](../../../apps/mission-control/src/preview/satellite.ts)
- [observation.ts](../../../apps/mission-control/src/preview/observation.ts)
- [model.ts](../../../apps/mission-control/src/preview/model.ts)
- [index.tsx](../../../apps/mission-control/src/pages/SatelliteIntel/index.tsx)
