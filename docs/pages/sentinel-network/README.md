# Sentinel Network

[All page guides](../README.md)

**Route:** `#/network` · **Keyboard shortcut:** `3` · **Status:** Current navigation page.

## Purpose and business value

Inspect the monitoring coverage behind a project's environmental evidence. Operators can see which devices are online, inspect their readings, and investigate gaps before relying on an assessment.

## Features

- Active node table and online count; decommissioned nodes are excluded from the active list.
- Selectable map pins and node rows.
- A node drawer with device details and a per-parameter chart history.
- A shared 15-minute telemetry chart window, combining HTTP history with live samples.
- Coverage and commissioning results, including gaps where available.
- Task timeline showing monitoring activity and commands.
- Zone tasking, task cancellation and node release controls.
- A confirmed re-commissioning action for recalculating network coverage.

## How to use it

1. Check the **Simulated hardware** badge and network online count.
2. Select a node in the table or on the map.
3. Read its detail drawer and charts, including the parameter units and timestamps.
4. Inspect coverage gaps before assuming a zone has sensor evidence.
5. Use the task controls to request monitoring for a covered zone.
6. Review the resulting timeline; use cancel or release controls when appropriate.

Re-commissioning is an operational action, not a visual reset. The interface asks for confirmation.

## Data and limitations

The prototype's Sentinel Nodes are simulated hardware communicating through the backend's MQTT workflow. A live chart means live simulator telemetry; it does not establish deployment of physical field sensors. The page requires the Ground Station, node registry and simulator/broker path to supply records and updates.

Coverage represents configured sensing reach, not proof that every point has a measured reading. Missing telemetry, offline nodes and gaps should remain visible in the assessment. Camera and network readiness are separate.

## Troubleshooting

If no nodes appear, confirm backend access and simulator registration. If readings stop updating, inspect the simulator, broker and WebSocket connection. If a zone cannot be tasked, check whether a qualifying water-quality or soil node covers it.

## Relevant implementation files

- [index.tsx](../../../apps/mission-control/src/pages/SentinelNetwork/index.tsx)
- [NodeCharts.tsx](../../../apps/mission-control/src/pages/SentinelNetwork/NodeCharts.tsx)
- [NodeDrawer.tsx](../../../apps/mission-control/src/pages/SentinelNetwork/NodeDrawer.tsx)
- [CoveragePanel.tsx](../../../apps/mission-control/src/pages/SentinelNetwork/CoveragePanel.tsx)
- [TaskTimeline.tsx](../../../apps/mission-control/src/pages/SentinelNetwork/TaskTimeline.tsx)
