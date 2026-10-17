# Digital Twin

[All page guides](../README.md)

**Routes:** `?mangrove-preview#/twin` (satellite-guided preview), `#/twin` (original Ground Station twin). **Keyboard shortcut:** `4`.

## Purpose and business value

Explore how a project looks spatially and discuss conditions that could affect mangrove wellness. Owners can test assumptions; partners and investors can inspect where a concern appears and what information supports it.

## Satellite-guided preview

The scene combines procedural trees, the selected satellite observation and a smooth risk field. Risk colours blend across the surface rather than appearing as stacked square boards. The underlying 25 analytical zones remain available for consistent inspection and editing.

### Scene and monitoring layers

| Group | Available controls |
|---|---|
| Main scene | 3D mangroves, satellite floor, continuous risk field, risk contours, water plane |
| Existing monitoring layers | Reality surface/live camera, risk columns, carbon columns, sensor nodes, coverage rings, tasking pulses, alert markers |
| Surface overlays | Satellite NDVI, satellite land-cover classes, camera NDVI-proxy and camera classes |
| Water and soil fields | Scenario values or live sensor interpolation; one surface field at a time |
| Display | Risk opacity and reality-surface vertical exaggeration |

Camera overlays require connected capture data aligned with the selected satellite footprint. Ground Station layers are hidden if the registered site does not match. **Show example layer data** supplies explicitly labelled visual examples; it does not send them to the backend.

### Attributes and units

| Attribute | Source in the default preview | Unit |
|---|---|---|
| Vegetation | Selected satellite NDVI | Index −1 to 1 |
| Water salinity | Scenario input | PSU |
| Dissolved oxygen | Scenario input | mg/L |
| Turbidity | Scenario input | NTU |
| Water temperature | Scenario input | °C |
| pH | Scenario input | pH |
| Soil salinity | Scenario input | PSU |
| Soil moisture | Scenario input | % |

Selecting **Live sensor interpolation (IDW)** changes the field overlay's data source; it does not convert the adjustable scenario risk calculation into a measured health assessment.

## How to use it

1. Check the shared satellite acquisition and let imagery load.
2. Drag to orbit and scroll to zoom.
3. Hover over an area for stress percentages and a short wellness explanation; click an area or use Zone selection to pin it.
4. Edit inputs for the selected zone, or choose **Edit whole site** to apply changes across all zones.
5. Enable/disable attributes and choose the highest enabled stress or one attribute with **Colour floor by**.
6. Try a surface overlay to inspect an individual field. Selecting an overlay clears the risk tint so the field remains visible.
7. Use **Reset scenario** to restore the scenario inputs, enabled attributes and combined floor.

## How to interpret colours and percentages

The combined floor takes the **highest enabled attribute stress**, expressed on a 0–100 scale. Green is below 30; yellow is 30–59; orange is 60–79; red is 80 or above. Grey means insufficient clear land or no enabled attributes. A zone needs at least 20% usable clear pixels to receive the preview's NDVI-based assessment.

A stress percentage is a model score, not probability of tree death, percentage of carbon eligible, or percentage of surveyed unhealthy trees. The field is visual interpolation between analytical zones; its soft edge is not a surveyed coastline. Soil-moisture and absolute-NDVI stress rules are illustrative. These scores are separate from backend fusion assessments.

## Original twin and limitations

The original route retains Ground Station surface, NDVI-proxy, classes, contours, risk/carbon columns, water/soil fields, network layers, trees, alerts and zone cards. It uses the shared Mapbox stage and backend records.

The preview's tree count, positions, height and response to stress are procedural estimates. Missing imagery is not filled with measured data. Scenario edits are component state; do not rely on them as saved project records when leaving or reloading the page. Use the ledger's request captures for its separate assessment history.

## Relevant implementation files

- [DigitalTwinPreview.tsx](../../../apps/mission-control/src/preview/DigitalTwinPreview.tsx)
- [ForestScene.tsx](../../../apps/mission-control/src/preview/ForestScene.tsx)
- [scenarioRisk.ts](../../../apps/mission-control/src/preview/scenarioRisk.ts)
- [WellnessCard.tsx](../../../apps/mission-control/src/preview/WellnessCard.tsx)
- [surfacePaint.ts](../../../apps/mission-control/src/preview/surfacePaint.ts)
- [ExtraLayers.tsx](../../../apps/mission-control/src/preview/ExtraLayers.tsx)
- [LayerPanel.tsx](../../../apps/mission-control/src/pages/DigitalTwin/LayerPanel.tsx)
