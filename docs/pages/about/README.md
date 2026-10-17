# About

[All page guides](../README.md)

**Route:** `#/about` · **Keyboard shortcut:** `0` · **Status:** Current About view.

## Purpose and business value

Introduce the project's identity and intended monitoring story. This page helps new stakeholders understand how observations, sensors, AI, the Digital Twin and the Carbon Ledger fit together.

## What is shown

- Blue Carbon Sentinel project name and Ocean Hackathon 2026/Kuala Lumpur context.
- Challenge title: KUL06 — Blue Carbon Sentinel: Autonomous Swarm-to-Satellite Edge AI Mangrove Restoration Network.
- The hardware clarification: **Fixed, anchored edge nodes — no drones, no swarm robotics.**
- A five-part pitch: where to investigate, why conditions change, possible futures, restoration decisions, and carbon value.
- Team attribution and GitHub owner name.

## How to use it

Open this view for an introduction, then move to Satellite Intelligence for project observations, Digital Twin for spatial exploration, or Carbon Ledger for the request/report workflow.

## Data and limitations

The cover content is static text defined in the frontend. It does not query a project valuation, calculate a credit price, verify sensor deployment, or certify an environmental outcome. The pitch describes the intended product story; consult each operational page's data labels and README for the current implementation and prototype boundaries.

There are no page-specific input forms or saved records. Shared shell connection badges may still reflect backend availability.

## Relevant implementation files

- [AboutCover.tsx](../../../apps/mission-control/src/shell/AboutCover.tsx)
- [NavRail.tsx](../../../apps/mission-control/src/shell/NavRail.tsx)
