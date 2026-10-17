# Carbon Ledger

[All page guides](../README.md)

**Route:** `#/ledger` (also works with `?mangrove-preview#/ledger`) · **Keyboard shortcut:** `5`.

## Purpose and business value

Create a farm-wide validation request, inspect the resulting creditable-area decisions, understand unclaimed credit potential per section, and retain assessment history. The request validates an area's eligibility; it is not a purchase request.

In this product, the user's term **carbon free** means **credits not already claimed**. It does not mean the land emits no carbon or that all stored carbon is available to sell.

## Request → process → receive report

1. Wait for the current satellite overview to load. Change the location or acquisition in Satellite Intelligence if needed.
2. Set the reporting period: start inclusive, end exclusive. Leave the verifier unassigned and add evidence/request notes as needed.
3. Keep **Simulate verifier processing** enabled to demonstrate the complete workflow.
4. Select **Submit farm validation request**. One request covers all 25 sectors automatically; there is no purchase/request button per sector.
5. The app freezes the current overview and records the request. The simulated workflow progresses through sent, processing and eligibility/prior-claim checks.
6. After about eight seconds, inspect the sample report, coverage map, section comparison and credit-balance views.

With simulation disabled, a request is saved locally as pending. No external verifier receives it automatically. Pending sections produce no credit quantity. Naming a verifier in the text field does not connect an API.

## Coverage and sector decisions

The fixed study extent is 500 × 500 m, or 25 ha, divided into A1–E5 analytical sections. Each section represents 100 × 100 m (1 ha). A returned section decision contains a 10 × 10 mask:

| Mask | Display meaning | Accounting meaning |
|---|---|---|
| `1` | Unclaimed creditable coverage | Mapped area available under that report's decision |
| `2` | Already-claimed coverage | Remains visible but is deducted from availability |
| `0` | Not creditable | Excluded from creditable coverage |

Select sections on the overhead map to inspect their coverage percentages, decision reason and reported quantities. Partial eligibility can occur within a section; other sections may be fully excluded. Dotted boundaries locate the sectors without opaque black sector boxes. Crediting coverage does not transfer land ownership.

Masks are report decisions, not a satellite classification of carbon-credit eligibility. An imported mask's 10 m analytical cell does not establish 10 m survey accuracy.

## Credit quantities and calculations

All quantities are in **tonnes of CO₂ equivalent (tCO₂e)**. These represent removal/credit accounting quantities, not tonnes of elemental carbon or hectares. The prototype does not issue registry credits.

For a received section decision:

```text
creditable area (ha) = count(mask cells 1 or 2) / 100
reported potential (tCO₂e) = received creditableTco2e
unclaimed before local sales = max(0, reported potential − received claimedTco2e)
available balance = unclaimed quantity after applicable local-sale deductions
```

The demo simulator uses an illustrative **8 tCO₂e/ha/year**, a varying eligibility pattern, and prior-claim examples. It is not an ecological estimate derived from satellite pixels, the Digital Twin's pH sliders, or independent verification. Changing twin scenario inputs does not drive these simulated credit decisions.

The underlying planning calculator also supports:

```text
years = reporting days / 365.25
net = area × (project rate − baseline rate − emissions rate − leakage rate) × years
potential = max(0, net) × (1 − uncertainty/100) × (1 − buffer/100)
unclaimed = max(0, potential − claimed)
```

Those planning terms are internal calculator capabilities, not an editable methodology form on the current request screen. In the report-receiving flow, report quantities are preserved through derived accounting rates with zero extra uncertainty/buffer deductions.

## Graphs and balance

The graph can show the whole farm or a selected reported section. It distributes report quantities at a constant rate across the reporting period. It is an **illustrative cumulative profile within one report**, not an observed issuance history or a sum of every request.

Section comparison bars show where reported quantities and claims sit across the farm. The credit balance accepts an amount, **Max** and **Sell**. This creates a **local sale record**, allocates it across sections, and reduces the displayed balance. Overlapping report periods reserve applicable prior local sales. **Undo** reverses the local record.

There is no payment processing, buyer settlement, registry transfer or actual marketplace execution.

## Overview capture stack and change tracking

Every new validation captures a frozen overview, capture time, satellite scene/acquisition time and coordinates. Selecting an older card restores that request and its report for review. Existing snapshot images are not overwritten.

Capture time and acquisition time are different. Repeated requests may capture the same satellite image when no newer acquisition exists. Simulations increment a condition revision to vary example eligibility; this is not evidence of observed land growth.

The change display compares gained/lost unclaimed-creditable cells in matching sections against an earlier completed assessment of the same simulation mode. Reports are separate assessments; overlapping snapshots are not added together as new credits. The current comparison is spatial coverage change, not a full carbon-stock change calculation.

## Receiving reports, exports and evidence

For the manual workflow, export a request and response template, populate the response JSON, then receive it through the page's report input. Validation checks IDs, mask format, decision reasons and quantities. A response may cover a subset of requested sections; unreported sections remain pending. Replacing an existing section decision requires a new request.

JSON validation does not authenticate the report issuer, prove ownership or check a registry. Simulation and non-simulation responses cannot be mixed.

Available outputs include request JSON with overview/evidence metadata, report CSV, report JSON with the captured image and accounting, and browser **Print / PDF**.

The **ICVCM Core Carbon Principles** list is an evidence blueprint. The app does not claim CCP certification. **Evidence & original ledger** opens the separate backend ledger with a plan checklist, zone eligibility, projected/demo records, record details and hash-chain verification. An intact hash chain checks record integrity; it does not certify a carbon credit.

## Storage and troubleshooting

Requests, responses and local sales are stored in browser `localStorage`. Overview images use IndexedDB (`bcs-carbon-overview-snapshots`). These are local to the browser profile and origin; changing host/port or clearing site data can make the history unavailable. They are not automatically cloud-synchronised.

- **Submit disabled:** wait for imagery/capture completion and any current simulation.
- **Pending forever:** with simulation off, a compatible report must be supplied manually.
- **No credits for a section:** inspect its report status, eligibility, prior claims and local sales.
- **Capture/storage error:** check browser storage availability; do not clear history before exporting important records.
- **Original ledger empty:** it needs the Ground Station and backend evidence; the local generator is separate.

## Relevant implementation files

- [Generator.tsx](../../../apps/mission-control/src/pages/CarbonLedger/generator/Generator.tsx)
- [verification.ts](../../../apps/mission-control/src/pages/CarbonLedger/generator/verification.ts)
- [simulation.ts](../../../apps/mission-control/src/pages/CarbonLedger/generator/simulation.ts)
- [model.ts](../../../apps/mission-control/src/pages/CarbonLedger/generator/model.ts)
- [snapshots.ts](../../../apps/mission-control/src/pages/CarbonLedger/generator/snapshots.ts)
- [sales.ts](../../../apps/mission-control/src/pages/CarbonLedger/generator/sales.ts)
- [index.tsx](../../../apps/mission-control/src/pages/CarbonLedger/index.tsx)
