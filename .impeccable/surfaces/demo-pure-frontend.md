---
version: 1
slug: "demo-pure-frontend"
primary_target: "Demo-Pure_Frontend"
related_targets: []
---

# Surface brief: Blue Carbon Sentinel demo (whole app, four pages)

**Scope and mode:** the whole frontend-only demo: shell plus Command Center, Satellite Intelligence, Sentinel Network and Digital Twin. Mode: **Operate** (a working dashboard a presenter drives live), with the maps and the 3D forest as the stage.

**Audience and job:** non-specialist visitors (judges, investors, community) watching on a laptop or projector; the presenter drives the story with one button per highlight (Prevention, Replantation).

**Constraints:** the PRD pins the light theme, colour tokens, Inter, type sizes, status words plus icons, page layouts and copy. Owner chose: sample photos labelled "Sample photo", laptop-only via start.cmd, no extras beyond the PRD.

**Memorable moment:** pressing Simulate danger and watching the whole site turn: cards drain to red, the banner follows, the camera is asked, the photo lands.

## Direction contract

THESIS: The forest's health is one signal that travels across every page. It refuses the category default of a grey grid of equal widgets: the maps and the 3D forest are the stage, and status colour is the only loud thing.

OWN-WORLD: The PRD's light world: mist ground #F6F8F7, white panels on 1px #DDE3E0 hairlines, deep teal #0F766E for actions and the active tab, and green/amber/red used as whole fields (the Level banner, each card's band) only where they mean something. Inter with tabular numerals, readings at 56px. Maps and the 3D forest run full-bleed inside 14px panels. One drawn icon set at a single stroke weight.

STORY: Visitors see where the sites are, fly into Kuala Selangor, compare the real satellite image with the 3D forest, watch readings fall into Danger and the camera respond, see a satellite scan find a replanting patch, then point anywhere in the forest to read all nine sensors.

FIRST VIEWPORT: Command Center: a full-bleed satellite globe framed on Malaysia; three tiles (Mangrove area, Forest health, Camera) across the top over the map; the Sites list overlaid on the left with Kuala Selangor first, its Fly to Kuala Selangor button the page's one primary action; pins on the globe, Kuala Selangor coloured by Level.

FORM: Brief-pinned (PRD decisions 4 and 10), position 1 of 1; seed: none (roll skipped: the PRD pins the direction). Signature move: the status colour travels. The danger ramp drains each sensor card green to amber to red, the banner field follows the worst card, and the same red pulses on the globe pin and blooms over the 3D forest around the station. Signature transition: the globe flies down and shrinks into the Satellite Intelligence left panel.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- None blocking. Camera failure states exist but only trigger when no photos are available.
