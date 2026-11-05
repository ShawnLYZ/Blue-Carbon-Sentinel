---
name: Blue Carbon Sentinel
description: A light, projector-legible field station where one health signal travels from sensor cards to the banner, the globe and the 3D forest.
colors:
  primary: "#0F766E"
  primary-hover: "#0B6159"
  primary-press: "#094F49"
  primary-soft: "#E3F1EF"
  healthy: "#2F9E44"
  healthy-ink: "#237A35"
  healthy-soft: "#EAF5EC"
  warning: "#F08C00"
  warning-ink: "#9A5300"
  warning-soft: "#FEF3E2"
  warning-edge: "#F5C67A"
  danger: "#E03131"
  danger-hover: "#C92A2A"
  danger-ink: "#B4232A"
  danger-soft: "#FDECEC"
  danger-edge: "#F0A0A0"
  scan-glow: "#7CF2D8"
  bg: "#F6F8F7"
  surface: "#FFFFFF"
  surface-2: "#EEF2F0"
  border: "#DDE3E0"
  border-strong: "#C9D2CE"
  text: "#14211C"
  muted: "#5B6B64"
  disabled-ink: "#5B6B64"
  map-well: "#DCE3DF"
  selection: "#BFE3DE"
  pin-soon: "#8E9A95"
  sky-loading: "#DCE7EC"
  photo-scrim: "rgb(0 0 0 / 0.62)"
  marker-shadow: "rgb(0 0 0 / 0.4)"
  scene-plain: "#aebcb1"
  scene-root: "#5b4b3b"
  scene-panel: "#1f2b33"
typography:
  display-reading:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "52px"
    fontWeight: 650
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontFeature: "'tnum', 'cv11', 'ss01'"
  display:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "48px"
    fontWeight: 650
    lineHeight: 1.05
    letterSpacing: "-0.025em"
    fontFeature: "'tnum', 'cv11', 'ss01'"
  headline:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title-panel:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "21px"
    fontWeight: 650
    lineHeight: 1.45
    letterSpacing: "-0.015em"
  title:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body-lead:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.4
  body:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'cv11', 'ss01'"
  button:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 600
  nav:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "14.5px"
    fontWeight: 600
    lineHeight: 1.2
  label:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 650
  label-sm:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "13px"
    fontWeight: 650
  brand:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "17px"
    fontWeight: 650
    letterSpacing: "-0.015em"
  dialog-title:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "22px"
    fontWeight: 650
    letterSpacing: "-0.015em"
  headline-short:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "24px"
    fontWeight: 700
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "27px"
    fontWeight: 650
    letterSpacing: "-0.02em"
  badge:
    fontFamily: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "12.5px"
    fontWeight: 700
    letterSpacing: "0.04em"
rounded:
  radius: "14px"
  inset: "12px"
  control: "11px"
  radius-sm: "10px"
  control-sm: "9px"
  radius-xs: "7px"
  menu-item: "8px"
  thumb: "6px"
  meter: "4px"
  indicator: "3px"
  dialog: "16px"
  pill: "999px"
spacing:
  pad: "20px"
  gap: "16px"
  short: "10px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-active:
    backgroundColor: "{colors.primary-press}"
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "46px"
  button-default-hover:
    backgroundColor: "{colors.surface-2}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "46px"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
  button-disabled:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.disabled-ink}"
  button-lg:
    padding: "0 24px"
    height: "52px"
  button-sm:
    rounded: "{rounded.control-sm}"
    padding: "0 14px"
    height: "36px"
  chip-healthy:
    backgroundColor: "{colors.healthy-soft}"
    textColor: "{colors.healthy-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 11px 0 9px"
    height: "30px"
  chip-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 11px 0 9px"
    height: "30px"
  chip-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 11px 0 9px"
    height: "30px"
  chip-sm:
    typography: "{typography.label-sm}"
    padding: "0 9px 0 7px"
    height: "24px"
  pill:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "32px"
  pill-outline:
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "32px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.radius}"
    padding: "16px 18px"
  panel-float:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.radius}"
  sensor-card-warning:
    backgroundColor: "{colors.warning-soft}"
  sensor-card-danger:
    backgroundColor: "{colors.danger-soft}"
  banner-healthy:
    backgroundColor: "{colors.healthy-soft}"
    textColor: "{colors.healthy-ink}"
    typography: "{typography.headline}"
    rounded: "{rounded.radius}"
    padding: "16px 22px"
    height: "92px"
  banner-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-ink}"
    typography: "{typography.headline}"
    rounded: "{rounded.radius}"
    padding: "16px 22px"
    height: "92px"
  banner-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.surface}"
    typography: "{typography.headline}"
    rounded: "{rounded.radius}"
    padding: "16px 22px"
    height: "92px"
  tab:
    textColor: "{colors.muted}"
    typography: "{typography.nav}"
    padding: "0 10px"
    height: "68px"
  tab-active:
    textColor: "{colors.text}"
  layer-toggle:
    textColor: "{colors.muted}"
    rounded: "{rounded.control-sm}"
    padding: "0 14px"
    height: "40px"
  layer-toggle-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
  badge-sample:
    backgroundColor: "rgb(20 33 28 / 0.74)"
    textColor: "{colors.surface}"
    typography: "{typography.badge}"
    rounded: "{rounded.radius-xs}"
    padding: "0 10px"
    height: "26px"
  badge-own:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
---

# Design System: Blue Carbon Sentinel

## Overview

**Creative North Star: "The Traveling Signal"**

Blue Carbon Sentinel is a calm, light field station built to be read from across a room on a laptop or a projector. The ground is a pale mist, panels are white, type is a deep forest ink, and a single estuary teal is the only colour that acts. Against that quiet, the forest's health is one signal (green, amber or red, always with a word and a drawn icon) and it travels: the sensor cards drain to the colour first, the Level banner follows the worst card, the same colour sits on the Kuala Selangor pin on the globe, and it blooms red over the 3D forest around the station. A visitor who catches any one of those places knows the state of the forest.

The maps and the 3D forest are the stage, not widgets in a grid. The satellite globe, the satellite footprint and a sunlit diorama of the 500 × 500 m forest square run full-bleed inside 14px panels, and the interface either floats over them on white panels with a soft shadow or sits on the mist ground with a single hairline. Density is low and the type is large on purpose: body text never drops below 16px, card titles below 20px or big numbers below 48px, at any screen size.

The world is pinned by the PRD (decision 4): a light theme, nine named colour tokens, Inter, and status words with icons. Two refusals are confirmed by the brief and the build: no grey grid of equal-weight widgets, and no status carried by colour alone.

**Key Characteristics:**
- Light mist ground, white panels, deep-ink text; teal is the only actor.
- Status is one travelling colour, always paired with a word and a drawn lucide icon.
- Every status hue has two shades: a bright mark colour and a darker ink shade for text.
- Maps and the 3D forest run full-bleed; UI floats over them or sits on hairlines.
- Large, tabular, projector-legible numbers; type floors hold at every breakpoint.
- The 3D forest is a diorama tile of cut earth under a physical sky.

## Colors

A restrained sage-and-ink neutral world with one teal actor and a three-step status palette that is the only loud thing on any screen.

### Primary
- **Estuary Teal** (#0F766E): the one colour that acts. Primary buttons ("Fly to Kuala Selangor", "Restore healthy", "Scan for replanting"), the active tab's filled numeral and 3px underline, the active Digital Twin layer, the focus ring, tile and caption icons, the Sentinel Station marker and the teal stripe on its 3D model, and the brand mark. White on it reads at 5.5:1.
- **Estuary Teal Deep** (#0B6159) and **Estuary Teal Deepest** (#094F49): hover and pressed states of the primary button, nothing else.
- **Estuary Teal Wash** (#E3F1EF): the live site's block in the Sites list and the "Pinned" tag on the Digital Twin hover card.

### Secondary: the status trio
- **Canopy Green** (#2F9E44), **Low-Tide Amber** (#F08C00), **Alarm Red** (#E03131): the PRD's status colours. They are used as marks and fields only: status icons, the camera-online dot, the globe pin, the sparkline's end dot, the station marker in danger, the danger pin pulse, the 3D bloom and the Digital Twin ramp. Alarm Red is also the solid field of the Level banner in Danger (white text at 4.5:1, set at 30px bold) and the fill of destructive or danger-causing buttons ("Simulate danger", "Reset").
- **Canopy Ink** (#237A35), **Amber Ink** (#9A5300), **Alarm Ink** (#B4232A): the text shades. Any status word set in type (chips, the Forest health tile, the banner word in Healthy and Warning, legend labels, the scan result heading, camera failure lines) uses the ink, never the bright colour. On their own washes they read at 4.8:1, 5.3:1 and 5.7:1.
- **Canopy Wash** (#EAF5EC), **Amber Wash** (#FEF3E2), **Alarm Wash** (#FDECEC): status chip backgrounds, the Healthy and Warning banner fields, sensor cards out of range, the scan result block and the Prevention action's icon tile.
- **Amber Edge** (#F5C67A) and **Alarm Edge** (#F0A0A0): the hairline of a sensor card in Warning or Danger, replacing the neutral border.
- **Alarm Red Deep** (#C92A2A): hover of the danger button.

### Tertiary
- **Scan Glow** (#7CF2D8): teal's lit form, reserved for the replanting scan: the sweeping line and its glow, and the outline and 28% fill of the patch the scan finds on the satellite map. Nowhere else.

### Neutral
- **Mangrove Mist** (#F6F8F7): the page ground under every page.
- **Panel White** (#FFFFFF): cards, floating panels, the top bar, dialogs; also the text colour on teal and red fills.
- **Pale Sage Well** (#EEF2F0): hover fill for tabs, icon buttons and default buttons; the top-bar pills; the "Coming Soon" tag; empty photo wells; disabled button fill.
- **Hairline Sage** (#DDE3E0): the 1px border of page cards and every divider (top bar, scan header, reading rows, dialog footer).
- **Firm Sage Line** (#C9D2CE): default button border, outline pill, inactive tab numeral ring, scrollbar thumb.
- **Deep Forest Ink** (#14211C): all primary text (15.6:1 on the ground); also the toast and the sparkline tooltip background, and the base of the scan and dialog scrims and the photo badge (`rgb(20 33 28 / 0.32–0.78)`). Only the photo lightbox goes darker, to a near-black scrim (`rgb(8 14 12 / 0.84)`).
- **Lichen Grey** (#5B6B64): secondary text: hints, units, subtitles, captions (5.3:1 on the ground, 5.0:1 on the sage well).
- Disabled button text uses **Lichen Grey** (#5B6B64, 5.0:1 on the sage well), because the disabled replant button spells out why it is unavailable.
- **Map Well** (#DCE3DF): the placeholder behind map panels before tiles paint.

### Named Rules
**The Traveling Signal Rule.** At any moment there is one forest status, and it shows in the same hue everywhere at once: sensor cards, the Level banner, the Forest health tile, the globe pin and the 3D forest. A new surface that shows health joins the signal; it never invents its own scale.

**The Two-Shade Rule.** Bright status colours are for marks and fields; ink shades are for words. Canopy Green fails text contrast on white (3.4:1) and Low-Tide Amber fails badly (2.5:1), so status text is always set in the ink shade.

**The Word-and-Icon Rule.** Colour never carries status alone. Under deuteranopia Canopy Green and Alarm Red are nearly the same colour, and under protanopia green and amber are; projectors wash all three out. Every status shows its word and its drawn icon: circle-check for Healthy, circle-alert for Warning, triangle-alert for Danger.

**The One Actor Rule.** Teal is the only non-status colour that acts. Red fills a button only when the action causes or clears danger or destroys state; Scan Glow belongs to the scan alone.

### The Digital Twin stress ramp
The Digital Twin paints each sensor layer with a continuous ramp from stress 0 (ideal) to 3 (deep danger), interpolated in OKLab between six stops: #2F9E44 at 0, #8DC63F at 0.85, #F08C00 at 1.2 (the healthy edge is at 1), #EE6A1B at 1.8, #E03131 at 2.15 (the danger edge is at 2) and #A61B1B at 3. The ramp starts and ends on the status colours so the forest speaks the same palette as the cards. The legend shows the ramp as a 12px bar with the three status words and icons beneath it, each in its ink shade.

## Typography

**Display Font:** Inter Variable (with Inter, system-ui, -apple-system, Segoe UI, sans-serif)
**Body Font:** Inter Variable (same stack)

**Character:** One family doing every job, self-hosted from the variable build so intermediate weights (550, 650, 750) are real. Character variants `cv11` and `ss01` are on globally for a clean single-storey a and open digits; every number that changes adds tabular figures so live readings do not jitter.

### Hierarchy
- **Display Reading** (650, 52px, 1.0, −0.03em, tabular): the live value on each sensor card, with its unit at 18px in Lichen Grey. Steps to 48px at widths up to 1240px and on short screens.
- **Display** (650, 48px, 1.05, −0.025em, tabular): Command Center tiles: the mangrove area number (unit at 20px), the Forest health word with its 30px status icon, and the camera's "Online" word with its dot.
- **Headline** (700, 30px, 1.1, −0.02em): the Level banner's status word. 24px on short screens.
- **Title Panel** (650, 21px, −0.015em): headers of panels holding lists or media: Sites, Camera, Station. Dialog and scan headers use the same weight at 22px.
- **Title** (650, 20px, 1.2, −0.01em): sensor names, action card titles (Prevention, Replantation), the scan result heading.
- **Body Lead** (400, 18px, 1.4): the banner's explanatory sentence; site names and site facts take 18px at weight 650.
- **Body** (400, 16px, 1.45): all running copy: sensor hints, tile subtitles, captions, legend keys, hover-card rows, dialog text, the toast.
- **Button** (600, 16px): every button; 17px on large buttons, 14px on small ones.
- **Nav** (600, 14.5px, 1.2): tab titles, with a 12.5px subtitle in Lichen Grey beneath.
- **Label** (650, 15px): status chips, pin and anchor labels; tile labels and layer buttons use 15px at 600.
- **Label Small** (650, 13px): small status chips and tab numerals.
- **Badge** (700, 12.5px, +0.04em, uppercase): only the photo provenance badge ("Sample photo", "ESP32-CAM photo").

### Named Rules
**The Floor Rule.** Body 16px, card titles 20px, big numbers 48px, at every breakpoint. Short screens (height up to 820px) find space in padding first: page padding and gaps drop from 20px and 16px to 10px, the top bar from 68px to 58px, card padding tightens and the camera photo goes from 4:3 to 2:1. Only sizes above a floor step down, and only to the floor (banner word 30→24px, sentence 18→16px, reading 52→48px).

**The Tabular Rule.** Any number that updates (readings, areas, coordinates, times, percentages) is set with tabular figures, and live readings glide to their new value over 1.3s rather than jumping.

## Layout

The app is a fixed-viewport stage, not a scrolling page: a 68px top bar over one page that fills the rest of the screen, with the body locked against scroll. Designed for 1366–1920px laptops and projectors, it holds at 1024px tablet landscape; phones are not targeted.

Each page has one spatial model:
- **Command Center:** a full-bleed globe. Three floating tiles (276px wide, 12px apart) sit across the top-left and the Sites panel (380px; 330px at widths up to 1100px) runs down the left beneath them. The globe's camera is padded so Malaysia frames in the space beside the panel.
- **Satellite Intelligence:** two equal panels side by side (the real satellite image and the 3D model of the same square), each with a one-line caption beneath, icon in teal, with the secondary fact right-aligned in Lichen Grey.
- **Sentinel Network:** a main column and a 400px side column (340px at widths up to 1240px). The Level banner spans the main column; the nine sensors sit in two rows on a 20-column grid (four water sensors span 5; two wave sensors and three air sensors span 4); at widths up to 1100px the grid drops to 12 columns, with water and wave sensors two-up and air sensors three-up; the two action cards sit two-up below and stack at 1100px. The side column holds the Camera and Station cards.
- **Digital Twin:** a full-bleed forest with floating controls at the edges: layer switcher centred at the top, Year at top-right, legend (420px) at bottom-left, hint at bottom-right.

Spacing is set by two variables: page padding (20px) and the gap between blocks (16px); both drop to 10px on short screens. Card interiors use 16–22px. Width breakpoints step the top bar down progressively: at 1660px the brand name wraps to two lines, at 1480px tabs tighten, at 1360px tab subtitles hide, at 1100px the brand name hides.

## Elevation & Depth

Elevation is declared once and follows where a surface sits. A surface that rests on the mist ground is flat with a 1px Hairline Sage border. A surface that floats over a map, the 3D forest or a scrim has no border and a soft, two-layer ambient shadow. Menus, dialogs and the toast sit one level higher with a deeper shadow. Shadows are never structural decoration.

The 3D forest carries its own physical depth: a cut tile of land under an atmospheric sky with real sun shadows, haze and a contact shadow on the plain below.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 1px 2px rgb(20 33 28 / 0.08), 0 10px 28px rgb(20 33 28 / 0.14)`): every panel over a map or the forest: tiles, Sites, popups, legend, layer switcher, hover card, pin and anchor labels, the north disc, the view-reset button, the scan dialog.
- **Pop** (`box-shadow: 0 2px 6px rgb(20 33 28 / 0.1), 0 18px 48px rgb(20 33 28 / 0.18)`): the overflow menu, modal dialogs, the toast.
- **Pin lift** (`box-shadow: 0 2px 8px rgb(0 0 0 / 0.35)`): map pins and markers over satellite imagery, under a white ring.

### Named Rules
**The Hairline-or-Float Rule.** A surface has a hairline or a shadow, never both. Page cards (sensor, camera, station, action) take the hairline; anything over a map, the forest or a scrim takes Float. Two lines are not elevation and may appear on either: a dashed outline, which means "planted", and a sensor card entering Danger, which sends out a single red ring that fades over 900ms.

## Shapes

Gently rounded and consistent, with radius stepping down as elements nest. Containers take 14px (cards, floating panels, the banner, map and forest panels); fields inset within them take 12px (the live site block, scan result, action icon tile, layer group, menu, toast, lightbox photo); buttons take 11px (9px small); media wells and icon buttons take 10px (camera photo, station and scan maps, view hint); badges and tooltips take 7px; dialogs take 16px. Small controls that state something (status chips, top-bar pills, "Coming Soon", "Pinned") are full pills. Circles mark points and steps: tab numerals, map pins, the banner's 54px icon disc, the north disc, the station marker.

Lines are few and meaningful: the 1px hairline, the 3px tab underline with rounded top corners, and dashes, which always mean "planted, grows next year" (white dashed patch outlines on the satellite map, a dashed key in the legend, a 1.5px dashed anchor label in the 3D view).

## Components

### Buttons
Solid, roomy and unambiguous, sized for a presenter clicking while talking.
- **Shape:** gently rounded (11px); 46px tall, 52px large, 36px small (9px radius); icon (18–19px) leads the label at a 9px gap.
- **Primary:** Estuary Teal fill, white label, 0 20px padding. Reserved for the step that moves the story forward ("Fly to Kuala Selangor", "Restore healthy", "Scan for replanting").
- **Default:** Panel White with a 1px Firm Sage Line border and ink label; hover fills with Pale Sage Well.
- **Danger:** Alarm Red fill, white label; hover Alarm Red Deep. Used for "Simulate danger" and the reset confirmation only.
- **Hover / Focus / Active:** colour shifts over 160ms ease-out; focus is a 2.5px teal outline 2px out; press nudges the button down 1px.
- **Busy and disabled:** a busy button swaps its icon for a spinner and its label for a present participle ("Dropping…", "Restoring…") and is disabled; disabled buttons take the sage well fill, hairline border and Lichen Grey text.

### Status chips
- **Style:** full pill, wash background, ink word, bright drawn icon at a 2.25 stroke (18px icon at 30px tall; 15px icon on the 24px small chip; 22px on the 40px large chip).
- **State:** one per status; background and colour cross-fade over 400ms when the status changes.

### Top-bar pills
- **Style:** 32px full pills at 14px/550: "Year N" and the camera status on Pale Sage Well; "Demo data" as an outline pill in Lichen Grey. The camera dot is green with a soft 3px halo when online, grey when offline.

### Cards / Containers
- **Corner Style:** 14px.
- **Background:** Panel White; out-of-range sensor cards take the status wash and edge colour, easing over 700ms.
- **Shadow Strategy:** see the Hairline-or-Float Rule.
- **Border:** 1px Hairline Sage on page cards; none on floating panels.
- **Internal Padding:** 16–20px on page cards, 14–18px on floating tiles.

### Navigation
- **Style:** one white top bar with a bottom hairline: brand mark and name, four numbered tabs, then status pills and the overflow menu.
- **Tabs:** a 24px circular numeral (1.5px sage ring, muted) beside a 14.5px title and 12.5px subtitle. Hover fills with Pale Sage Well. The active tab fills its numeral with teal and grows a 3px teal underline from the centre over 220ms. Keys 1–4 switch pages.
- **Responsive:** subtitles hide at 1360px; the brand name hides at 1100px.

### Level banner
The page-wide verdict on the Sentinel Network. A 54px white disc holds a 32px status icon, then the 30px status word and an 18px sentence naming the sensors at fault, with a blinking "Live · every 2 s" at the right. Healthy and Warning use the wash with an ink word; Danger turns the whole field Alarm Red with white text. The field cross-fades over 600ms.

### Sensor card
Name (20px), small status chip, one-line plain hint, then the reading (52px tabular, unit beside it) over a 40px sparkline of the last five minutes. The line is a neutral 2px grey, the healthy range is a faint green band behind it, and only the end dot takes the status colour (with a 2px white ring). Hovering the line reads any point with its time.

### Layer switcher
A floating segmented group (12px radius, 4px inset) of 40px buttons: "Natural" plus one per sensor. The pressed layer fills teal with white text; others are muted and fill with the sage well on hover.

### Map pins and markers
The live site's pin is a 26px disc filled with the current status colour inside a 3.5px white ring, labelled by a white chip with the Float shadow; in Danger it pulses two red rings outward every 1.8s. Coming-soon sites are 16px grey pins (#8E9A95). The Sentinel Station marker is a 34px teal disc with a white camera icon, turning red in Danger.

### Photo provenance badge
A small 7px-radius tag in the photo's top-left corner: dark translucent ink with a 6px backdrop blur reading "Sample photo" for shipped samples, teal reading "ESP32-CAM photo" for the owner's own. It is the only uppercase type in the system.

### Forest diorama (signature)
The 3D forest is a 500 × 500 m tile of land lifted out of the world: procedural Rhizophora-like trees and breathing roots placed from the real canopy outlines, a river with a grazing-angle sky sheen, and cut edges of layered mud with the water's cross-section where a channel meets the edge. It sits on a soft sage plain with a blurred contact shadow, under a physical sky (late-morning sun at 45° elevation from the east-south-east, light haze, filmic tone mapping) with real shadows. In Natural mode it shows true colours, except that readings outside the healthy range bloom over the forest around the station in the ramp's colour, red in Danger; sensor layers paint the stress ramp across the ground and canopy. In the Digital Twin the Sentinel Station stands as a white pole and box with a teal stripe and a dark solar panel.

### Hand-over transition (signature)
"Fly to Kuala Selangor" flies the globe down to the site over 3s, then the last frame shrinks from full screen into the Satellite Intelligence left panel over 620ms while the 3D view fades in. Other page changes cross-fade in 220ms. With reduced motion the fly becomes a 0.5s fade.

## Do's and Don'ts

### Do:
- **Do** pair every status colour with its word and its drawn icon: circle-check Healthy, circle-alert Warning, triangle-alert Danger.
- **Do** set status words in the ink shades (#237A35, #9A5300, #B4232A) and keep the bright status colours for icons, dots, pins, fields and the ramp.
- **Do** keep body text at 16px or more, card titles at 20px or more and big numbers at 48px or more at every screen size; take space from padding first.
- **Do** give page cards a 1px #DDE3E0 hairline and no shadow, and give anything floating over a map, the forest or a scrim the Float shadow and no border.
- **Do** let a status change move as a colour field easing out over 400–700ms, so the signal visibly travels.
- **Do** set every changing number in tabular figures.
- **Do** run maps and the 3D forest full-bleed inside 14px panels.

### Don't:
- **Don't** set Canopy Green (#2F9E44) or Low-Tide Amber (#F08C00) as text on white or on their washes; they fail contrast.
- **Don't** let colour alone say healthy, warning or danger.
- **Don't** draw status with text glyphs (✓ ! ⚠); use the drawn icons.
- **Don't** shrink type below its floor to fit a short or narrow screen.
- **Don't** fill a sensor card with a bright status colour; cards take the wash and edge, and only the Level banner takes the solid Alarm Red field.
- **Don't** introduce a second action colour; teal acts, red only causes or clears danger, and Scan Glow belongs to the scan.
- **Don't** combine a hairline and a shadow on the same resting surface.
- **Don't** build dark page surfaces; dark ink is reserved for the toast, the photo badge, the sparkline tooltip and scrims.
- **Don't** cover the Mapbox logo or attribution on any map.
