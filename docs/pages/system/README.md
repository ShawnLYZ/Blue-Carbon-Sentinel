# System

[All page guides](../README.md)

**Route:** `#/system` · **Keyboard shortcut:** `6` · **Status:** Current navigation page.

## Purpose and business value

Check whether the infrastructure behind the project evidence is working. This is an operator/administrator page for diagnosing capture quality, monitoring readiness and service dependencies.

## Sections

| Section | What it provides |
|---|---|
| Camera | Connection, camera settings, exposure/white-balance lock, orientation and reconnect controls |
| Live surface | Frame rate, server/browser processing latency and age of the newest rendered frame |
| Calibration | Current calibration details and a confirmed reset action |
| Commissioning | Commissioning state and network re-commissioning access |
| Device registry | Registered device status/firmware and node-key regeneration |
| AI | Provider/key-slot status, usage information and local-model status |
| Cloud | Cloud synchronisation status and buffering information |
| Versions | Reported component versions |

## How to use it

1. Check camera, live-surface and cloud status before presenting a connected demo.
2. Review calibration if capture geometry or zone alignment looks wrong.
3. Inspect commissioning and device status if sensor coverage is incomplete.
4. Review AI and version details to diagnose a provider or deployment issue.
5. Use operational actions only when needed; follow the confirmation dialogs for calibration reset, re-commissioning and key regeneration.

These controls affect the configured backend/device system. Regenerating a node key changes device credentials; it is not a cosmetic UI action.

## Data and limitations

This page depends on Ground Station status/configuration services and whichever components are actually configured. A frontend-only preview can show unavailable sections. AI key status uses slot information rather than revealing provider API key values. Newly regenerated device credentials are handled in a dedicated reveal/copy workflow.

Live surface performance targets displayed in the UI (at least 5 fps, at most 500 ms) are targets, not a guarantee that the running machine achieves them. No live frame received means no performance observation exists yet.

## Troubleshooting

Investigate the specific failing component rather than interpreting every red/offline badge as a page failure. The open satellite preview can work while local camera, broker, AI or cloud services are unavailable. See the repository runbook for deployment and recovery instructions.

## Relevant implementation files

- [index.tsx](../../../apps/mission-control/src/pages/System/index.tsx)
- [CameraSection.tsx](../../../apps/mission-control/src/pages/System/CameraSection.tsx)
- [CalibrationSection.tsx](../../../apps/mission-control/src/pages/System/CalibrationSection.tsx)
- [DeviceRegistrySection.tsx](../../../apps/mission-control/src/pages/System/DeviceRegistrySection.tsx)
- [LiveStatsSection.tsx](../../../apps/mission-control/src/pages/System/LiveStatsSection.tsx)
- [AiSection.tsx](../../../apps/mission-control/src/pages/System/AiSection.tsx)
- [CloudSection.tsx](../../../apps/mission-control/src/pages/System/CloudSection.tsx)
