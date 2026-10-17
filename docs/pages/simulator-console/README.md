# Simulator Console — supporting application

[All page guides](../README.md)

**Built-app path:** `/console/` · **Development port:** `5174` · **Status:** Separate supporting application; not a Mission Control sidebar page.

## Purpose and business value

Generate repeatable monitoring demonstrations without deploying physical sensors. Operators can show how node telemetry, environmental scenarios and network changes affect the connected system.

## Features

| Area | What it does |
|---|---|
| Header | Shows simulator/broker connection, demo-time mode and fast-forward rate |
| Site mini-map | Supplies spatial context and point selection for device operations |
| Nodes | Shows simulator nodes and streamed values |
| Scenarios | Applies a selected scenario to a chosen zone with a ramp time |
| Natural behaviour | Controls tide, spring-neap/diurnal effects, noise, tide settings and fast-forward |
| Lifecycle | Installs, moves and removes simulated nodes |
| Packet inspector | Inspects simulator/protocol activity |
| Record/replay | Records sessions and replays them with simulation labels |

Scenario presets include sediment runoff, salt intrusion, low oxygen, heat stress, heavy rain, healthy and recovery.

## How to use it

1. Start the configured Ground Station, simulator and broker services.
2. Open `/console/` from the built Ground Station app, or use `http://127.0.0.1:5174/console/` when its development server is running.
3. Check simulator and broker connection badges.
4. Select a zone and apply a scenario; inspect node values and the connected Mission Control views.
5. Clear or change scenarios when preparing the next demonstration.
6. Use session recording/replay for repeatability. Move/remove operations present confirmation dialogs.

## Data and limitations

This is explicitly **SIMULATED HARDWARE**. The simulator supplies telemetry through its configured service and broker; the console also uses Ground Station public configuration. It is not a separate source of measured field evidence or independent carbon validation.

The Carbon Ledger's eight-second verifier simulation is a different browser-local workflow. Changing a simulator environmental scenario does not, by itself, produce an independently verified carbon-credit report.

## Troubleshooting

A running frontend does not make the simulator online. Check public configuration, simulator reachability, broker connectivity and the stream status. Panel errors can be retried independently without reloading every console region.

## Relevant implementation files

- [ConsoleShell.tsx](../../../apps/sim-console/src/shell/ConsoleShell.tsx)
- [ScenarioPanel.tsx](../../../apps/sim-console/src/scenarios/ScenarioPanel.tsx)
- [NaturePanel.tsx](../../../apps/sim-console/src/nature/NaturePanel.tsx)
- [LifecyclePanel.tsx](../../../apps/sim-console/src/lifecycle/LifecyclePanel.tsx)
- [RecordReplay.tsx](../../../apps/sim-console/src/recording/RecordReplay.tsx)
- [vite.config.ts](../../../apps/sim-console/vite.config.ts)
