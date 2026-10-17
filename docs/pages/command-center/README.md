# Command Center

[All page guides](../README.md)

**Route:** `#/command` · **Keyboard shortcut:** `1` · **Status:** Current navigation page.

## Purpose and business value

The operational starting point for reviewing a monitored project. Owners and partners can check whether the monitoring system is connected, identify high-risk zones, and decide where to investigate next.

## What the page contains

| View | What it means |
|---|---|
| Camera | Current Ground Station camera connection status |
| Sentinel Network | Registered nodes online out of the active network |
| Mangrove health | Canopy-weighted camera vegetation proxy relative to zone baselines |
| Active risks | Zones whose latest backend assessment is high or critical |
| Water quality | Worst configured stress class across online water-quality nodes |
| Carbon stock | Estimated standing stock in tCO₂e; distinct from credit availability |
| Verified demo credits | Backend demo ledger quantities; not certified credits |
| Sites | Monitored site and planned sites, with rationale cards |
| Alerts | Operational alerts with severity, occurrence information and acknowledgement |

The map provides project context. Planned locations are labelled **planned — not yet monitored**.

## How to use it

1. Check the top-level connection badges before interpreting figures.
2. Review the KPI tiles; their tooltips explain each source.
3. Inspect alerts and acknowledge an alert after reviewing it.
4. Use the Sites panel to inspect a planned site's rationale or return to the monitored site.
5. Continue to Satellite Intelligence, Sentinel Network or Digital Twin for investigation.

## Data and limitations

This page reads Ground Station status, node registry, zone metrics, assessments, alerts and carbon summaries. Capture events refresh zone summaries; the alert list also refreshes periodically. Acknowledgement updates backend alert state.

A camera NDVI-proxy is an RGB vegetation proxy (VARI), not Sentinel-2 NDVI. A missing value, offline badge or loading state does not indicate a healthy project. Frontend-only previews do not provide the backend information required to populate this page. Planned sites are not additional monitored assets.

## Troubleshooting

- **Empty figures:** confirm the Ground Station is running and the browser can reach its API and WebSocket.
- **Blank map:** check the configured public Mapbox token and browser WebGL support.
- **No health comparison:** a usable capture and zone baseline are required.

## Relevant implementation files

- [index.tsx](../../../apps/mission-control/src/pages/CommandCenter/index.tsx)
- [KpiTiles.tsx](../../../apps/mission-control/src/pages/CommandCenter/KpiTiles.tsx)
- [kpis.ts](../../../apps/mission-control/src/pages/CommandCenter/kpis.ts)
- [AlertFeed.tsx](../../../apps/mission-control/src/pages/CommandCenter/AlertFeed.tsx)
- [PlannedSites.tsx](../../../apps/mission-control/src/pages/CommandCenter/PlannedSites.tsx)
