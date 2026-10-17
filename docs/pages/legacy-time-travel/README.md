# Time Travel & Restoration — legacy

[All page guides](../README.md)

**Route:** `#/time-travel` · **Status:** Retained legacy route; removed from navigation and keyboard shortcuts.

## Why this README exists

The Time Travel & Restoration tab was removed from the current website navigation as requested. Its code and direct hash route still exist for compatibility. This documentation records that state; it does not restore or recommend the tab as part of the current product walkthrough.

## Retained functionality

The legacy view contains linked “without restoration” and “with restoration” maps, a 2026–2035 year slider, scenario figures, uncertainty charts, and a restoration-plan editor. Users can select a zone, edit interventions and run forecasts when backend evidence and services are available.

The view preloads forecast/media information so moving the year slider does not require a new forecast request for every position. The shared stage is hidden while this route presents its own maps.

## Data and limitations

Forecasts require Ground Station site, capture, plan and forecast records. Visual future illustrations can be optional or unavailable; they are not observations. Scenario quantities and uncertainty bands are modelling outputs, not verified future removals or promises of issued credits.

The original Digital Twin can still contain a legacy link to this route. Absence from the sidebar does not mean the route/component was deleted. Current assessment history and coverage changes are presented in Carbon Ledger; those snapshots are separate from this legacy future-scenario feature.

## Maintenance note

Keep this guide marked legacy unless navigation and product scope are deliberately changed. Use the current page index when preparing business demos.

## Relevant implementation files

- [index.tsx](../../../apps/mission-control/src/pages/TimeTravel/index.tsx)
- [useTimeTravel.ts](../../../apps/mission-control/src/pages/TimeTravel/useTimeTravel.ts)
- [PlanEditor.tsx](../../../apps/mission-control/src/pages/TimeTravel/PlanEditor.tsx)
- [router.ts](../../../apps/mission-control/src/shell/router.ts)
