# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite + TypeScript, three.js for the 3D forest, Mapbox GL JS for the maps, zustand for client state. Chosen to match the PRD (decision 2). The owner confirmed on 17 October 2026 that this demo runs on their laptop only: double-click `start.cmd`, which serves it at http://localhost:5173. No online hosting.

## Users

- **Visitors:** judges, investors and community members watching a live demo on a laptop or a projector. They are not specialists. They need to tell at a glance what the system does and whether the forest is healthy.
- **The presenter (the owner):** drives the story page by page during a demo, using buttons and the number keys 1–4, and resets the demo between audiences.

## Product Purpose

Blue Carbon Sentinel watches a mangrove forest at Kuala Selangor Nature Park, Selangor, Malaysia. It tells one story in four pages: where the sites are, what the forest looks like from space and in 3D, how healthy it is right now (with a camera that photographs trees in danger), and what conditions are at any point in the forest.

This folder is a **frontend-only demo** of that product. There is no backend, database or real hardware. Every sensor value, the camera and the replanting scan are simulated in the browser. Success means a non-technical visitor follows the whole story without help, and the presenter can run Prevention and Replantation with one button each.

## Positioning

Two highlight features, each shown with one button:

- **Prevention:** readings slide into Danger, and the camera automatically photographs the tree in danger.
- **Replantation:** a satellite scan finds a real empty patch where conditions are healthy and says how many seedlings fit there.

The 3D forest is placed from the real satellite image of the same 500 × 500 m square, so the model visibly matches reality.

## Operating Context

- Shown on a 1366–1920 px laptop screen or a projector; must still work at 1024 px (tablet landscape). Phone layouts are not targeted.
- Live demo conditions: the presenter talks while clicking, so states must read from across a room.
- Demo script: Command Center → Fly to Kuala Selangor → Satellite Intelligence → Sentinel Network (Simulate danger, Restore healthy, Scan for replanting) → Digital Twin → ⋯ → Reset demo.

## Capabilities and Constraints

- Four pages only, in story order, as hash routes: `#/command`, `#/satellite`, `#/network`, `#/twin`.
- Vocabulary, Sensor Ranges, the Field Model and page contents follow `Final_PRD.md` (decisions 1, 4, 5, 8, 9, 10 and 21) and its build addendum.
- **Simulated in this demo:** the nine Sensors, the danger and restore ramps, the camera (heartbeat, photo requests, photos), the replant scan and plantings, and Demo Reset. State that the PRD keeps in Supabase is kept in the browser instead, so a reload keeps the danger state, plantings and photo history.
- **Camera photos:** the owner chose shipped, freely licensed sample mangrove photos labelled "Sample photo", never "LIVE CAMERA". The owner can drop their own ESP32-CAM JPGs into the `camera-photos` folder to replace them.
- **Monitoring Year** stays at 1; nothing advances it (owner decision).
- **Canopy Outlines:** traced once from Mapbox Satellite (PRD addendum A0.1, option A, non-commercial). Only polygons are stored; no Mapbox pixels are saved in the project.
- Mapbox attribution and logo stay visible on every map.
- The owner chose to follow the PRD exactly: no guided tour or other extras.

## Brand Commitments

- Name: **Blue Carbon Sentinel**.
- Light theme with the PRD's colour tokens (Background #F6F8F7, Surface #FFFFFF, Border #DDE3E0, Text #14211C, Muted #5B6B64, Primary #0F766E, Healthy #2F9E44, Warning #F08C00, Danger #E03131).
- Inter. Body 16–18 px, big numbers 48–64 px, card titles 20–24 px.
- Every status shows a word and an icon as well as colour: Healthy (check), Warning (exclamation), Danger (warning triangle).
- One small "Demo data" badge replaces all disclaimers.
- English only, plain words, each Sensor with its standard name and a one-line plain hint. Times in Malaysia time (MYT), en-MY formatting.

## Evidence on Hand

- The real satellite image of the Footprint (via Mapbox, at run time).
- Real site facts: Kuala Selangor Nature Park, Footprint centre 3.33656° N, 101.23674° E, 500 × 500 m (25 ha).
- **Not on hand:** real sensor data, real camera photos from the site, any customer, partner or funding claims. Nothing of the kind may be invented.

## Product Principles

1. **One story, four steps.** Every page continues the previous one; nothing appears that the story does not need.
2. **Status is read, not decoded.** Green, amber and red mean the same thing everywhere, always with a word and an icon.
3. **Honest simulation.** Simulated values are marked once by the "Demo data" badge; photos are never passed off as live.
4. **The model matches the place.** The 3D forest stands where the satellite image shows forest.

## Accessibility & Inclusion

- Status never relies on colour alone (projectors wash colours out; colour-blind visitors).
- Readable from across a room: large numbers and body text.
- Reduced motion: the fly-in becomes a 0.5 s fade, the scan sweep becomes a fade, card animations calm down; ramp timing is kept because it is part of the story.
