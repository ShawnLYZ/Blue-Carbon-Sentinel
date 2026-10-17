# Website page READMEs

These guides describe the current website, including the open satellite/digital twin preview and the original Ground Station views. Start with the [main repository README](../../README.md) for an overview, setup and the [satellite dataset](../../datasets/kuala-selangor/README.md).

## Current website pages

| Page | README | Main route | Main value |
|---|---|---|---|
| Command Center | [Read guide](command-center/README.md) | `#/command` | Review project monitoring status and alerts |
| Satellite Intelligence | [Read guide](satellite-intelligence/README.md) | `?mangrove-preview#/satellite` | Inspect observations, acquisition dates and site context |
| Sentinel Network | [Read guide](sentinel-network/README.md) | `#/network` | Inspect monitoring nodes, telemetry and coverage |
| Digital Twin | [Read guide](digital-twin/README.md) | `?mangrove-preview#/twin` | Explore the landscape, attributes and scenario risks |
| Carbon Ledger | [Read guide](carbon-ledger/README.md) | `#/ledger` | Request validation, review potential and track assessment history |
| System | [Read guide](system/README.md) | `#/system` | Check infrastructure and device readiness |
| About | [Read guide](about/README.md) | `#/about` | Introduce the project and its intended workflow |

## Supporting and retained views

- [Simulator Console](simulator-console/README.md): separate application at `/console/`, used for simulated sensor demonstrations.
- [Time Travel & Restoration — legacy](legacy-time-travel/README.md): direct route retained, but its tab and keyboard shortcut are removed.

The original evidence ledger is a subview of Carbon Ledger, so its documentation is included in that page's guide. The Demo Director and shared top bar/map controls belong to the application shell rather than separate routes.

## Opening the local website

From the repository root, with dependencies already installed:

```sh
pnpm --filter @bcs/mission-control dev --host 127.0.0.1
```

Open `http://127.0.0.1:5173/?mangrove-preview#/satellite` or `http://127.0.0.1:5173/?mangrove-preview#/twin`. Keep the development server running. These are local addresses, not public hosting links. The port may differ if Vite reports it is already occupied.

The `mangrove-preview` query flag replaces Satellite Intelligence and Digital Twin only. Without it, those routes use their original Ground Station components. Other pages retain their usual implementations. Use explicit hash routes; the router falls back to Command Center when no recognised hash is present.

The Mission Control development server proxies `/api` and `/ws` to the Ground Station at `127.0.0.1:8700`. Backend-dependent pages need that service. The original Mapbox stage needs its configured public token. The open satellite preview reads external imagery directly and needs internet access; WebGL is required for its 3D scene.

Full-system setup remains in the [repository README](../../README.md) and [runbook](../runbook.md). These page guides do not replace installation instructions.

## Shared interpretation rules

- **Observed imagery:** read the satellite acquisition date and masking/quality indicators. It is not live video.
- **Modelled geometry and scenarios:** estimated trees and adjustable environmental inputs support exploration; they are not field measurements.
- **Simulator telemetry:** streamed demo node readings are explicitly simulated hardware.
- **Credit potential:** report quantities are in tCO₂e. Stock, creditable area, unclaimed quantities and registry-issued credits are different concepts.
- **Verification:** local simulations, imported report JSON and hash-chain integrity do not establish independent certification or registry issuance.
- **History:** browser-local captures/reports are separate assessments. Repeating a request does not automatically add new carbon credits or produce a newer satellite acquisition.

## Guide format

Each README covers purpose/business value, features, usage, data interpretation, current limitations, and relevant source files. Additional details appear where the page needs them, including ledger calculations, browser storage and layer attributes.
