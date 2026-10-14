# Manual camera checklist (real ESP32-CAM only)

Run through `scripts/start.ps1` with the real ESP32-CAM. Tick each line only when its measurable expectation is met, and record numbers in the results table at the end. Section 6 needs the tank and belongs to M7.

## 0. Firmware bring-up (deferred from M2 Task 2)

- [ ] Camera on its MB programmer, plugged into the laptop; `pio device list` shows the port.
- [ ] `scripts/fw.ps1 upload` ends with "Hard resetting via RTS pin".
- [ ] Serial prints `SentinelCam <fw_version> booting` and `portal: SentinelCam-Setup`.
- [ ] From a phone, join "SentinelCam-Setup" and choose the 2.4 GHz network; the portal closes and the camera joins within 30 s.
- [ ] `curl http://sentinel-cam.local/status` returns JSON with `device_id` = `CAM-01`.
- [ ] `curl -s -o NUL -w "%{http_code}" http://sentinel-cam.local/capture` prints `401` (no token).
- [ ] A second concurrent `/stream` client gets HTTP `503`; the first client keeps streaming.
- [ ] `/stream?token=<token>` and `/capture?token=<token>` return `200`.
- [ ] Double reset within 5 s opens the `SentinelCam-Setup` portal again.
- [ ] `ae_lock` on: no visible brightness flicker over 60 s of the stream.
- [ ] `awb_lock` on: colours of a fixed scene do not shift over 60 s (no visible tint change).
- [ ] `scripts/fw.ps1 upload-ota` (password from `.env`) succeeds and the camera reboots on the new `fw_version`; a wrong password is rejected.

## 1. Setup

- [ ] First USB flash works end to end (section 0).
- [ ] Captive setup portal appears within 10 s of first boot and accepts credentials.
- [ ] Joins the 2.4 GHz network; `/status` shows the camera on the LAN IP.
- [ ] mDNS: `sentinel-cam.local` resolves from the laptop within 5 s.
- [ ] OTA update succeeds (section 0).
- [ ] Token enforcement: `/capture` and `/stream` without token return `401`; with token return `200`.

## 2. Stream and settings

- [ ] Stream at SVGA: at least 8 fps (System page `fps_in`).
- [ ] Stream at XGA: at least 5 fps (System page `fps_in`); record actual.
- [ ] Flip and mirror toggles change the image orientation within 2 s and persist after a reboot.
- [ ] Exposure lock and white-balance lock: colour of a fixed grey card varies by at most a visible-free margin (no flicker) over 60 s.
- [ ] Flash LED stays off during stream and during captures.

## 3. Live 3D

- [ ] Default calibration loads without manual input and produces a surface on the map.
- [ ] Live surface at least 5 fps (System page, "Live surface" panel, "Surface rate") on: desk, potted plant, moving hand. Read it after 10 s on each scene.
- [ ] Frame to screen at most 500 ms (System page, "Live surface" panel, "Frame to screen" = "Server latency" from the frame header `latency_ms` + "Browser receive → upload") on each scene. Record all three numbers. The same newest sample is in the browser console as `window.__bcsLive` (`serverLatencyMs`, `receiveToUploadMs`).
- [ ] North-up orientation: place a small marker at the top edge of the camera view; on the map it lands on the site's north edge (top of the site square), not on another side. Move it to the left edge: it lands on the west edge.
- [ ] Depth mode vs fallback mode: switching shows the matching mode label and the surface keeps updating.
- [ ] Vertical exaggeration slider changes relief height live and the value persists after a reload.

## 4. Captures

- [ ] A capture is stored every 10 s (+/- 1 s) for 2 minutes.
- [ ] Change capture fires about 2 s after the hand leaves the view, and not while it is moving.
- [ ] Quality marks: a blurred or over-/under-exposed frame is marked as poor; a normal frame is marked good.
- [ ] With exposure locked and a baseline set, adding a plant to a zone raises `new_growth`; removing it raises `canopy_loss`.

## 5. Failure and recovery

- [ ] Unplug the camera: offline banner within 3 s and the last frame stays frozen.
- [ ] (M4, not run in M2) An alert is raised when the camera goes offline and another when it comes back (the camera offline/online callbacks are wired to alerts in M4).
- [ ] Reconnect the camera: banner clears and the stream resumes without manual action (within 30 s).
- [ ] After the reconnect with exposure locked: the System page shows "Exposure / WB: locked (confirmed by the camera)" within 5 s, and `/status` shows `ae_locked` and `awb_locked` true.
- [ ] Frame size HD: choose HD on the System page; `/status` shows `frame_size` `HD` and the stream keeps running.
- [ ] Weak power (e.g. low-current USB port): record behaviour (brownout reboots, fps drop); camera recovers on its own after power is restored.

## 6. With the tank (M7)

Not run in M2.

- [ ] 4-corner calibration and north edge.
- [ ] Commissioning on real water, mud and shore.
- [ ] Flags for a browned tree and a removed tree.
- [ ] New growth from clay saplings.
- [ ] Sediment-plume tint.
- [ ] Threshold tuning.
- [ ] Full Demo Director loop.

## Site check (M1 deferred follow-up)

- [ ] Eyeball the Kuala Selangor site square on the map: NW corner 3.338807 N, 101.234489 E. It was chosen from a single image in M1; confirm it covers the intended mangrove area, otherwise adjust.

## AI and risk (M4)

Run 2026-10-12 (M4 Task 12) without the camera (`sentinel-cam.local` did not resolve). The camera and Wi-Fi steps were replaced by the automated equivalents below; the hands-on versions stay open for the next hardware session.

| Check | Expected | Measured (2026-10-12) | Result |
|-------|----------|-----------------------|--------|
| Gemini online: `scripts\start.ps1`, simulator nodes online, `POST /api/v1/zones/{zone}/analyze` on KSL-C3 (WQ-01) and KSL-E3 (SP-02) | Assessment with a Gemini narrative, chip "Gemini 2.5 Flash" (or "3.1 Flash-Lite"), confidence components, attempts in `ai_calls` | Both zones: tier `gemini_primary` (`gemini-2.5-flash`), narrative present, confidence camera/sensor/prediction/overall present, request to stored AI assessment 3.0 s and 2.6 s; `GET /api/v1/ai/calls` holds both attempts (`success`, 2.7 s and 2.4 s, key slots 1 and 2) | Pass |
| Fallback: Ground Station restarted with its Gemini traffic sent to an unreachable proxy (`HTTPS_PROXY=http://127.0.0.1:9`, Ollama exempt via `NO_PROXY`; `.env` untouched), analyse KSL-C3, KSL-E3, KSL-B1 | Chip "Gemma 4 · local" or "Rules"; one `ai_degraded` alert per role | All three: tier `gemma_local` (`gemma4:e4b`), elapsed 41.0 s (Gemma cold load), 23.6 s, 24.1 s; `ai_calls` per request: `gemini_primary` unavailable (ConnectError, ~2.4 s), `gemini_secondary` unavailable (~2.0 s), `gemma_local` success (36.4 s cold, 18.9 s and 19.4 s warm); one `ai_degraded` alert for `risk_interpreter` with `occurrences` 3 | Pass (risk_interpreter only) |
| Reconnect: Ground Station restarted normally, analyse KSL-C3 again | Gemini answers again | tier `gemini_primary`, 2.6 s | Pass |
| Early warning: `early-warning-salt.yaml` run through the simulator's `POST /api/v1/scenario-runs` (salt intrusion on E3/E4, SP-02 porewater held at 58 PSU from 240 s), canopy unchanged (seeded baseline and capture) | Alert "Sub-canopy stress — not yet visible from orbit"; automatic task with trigger `early_warning`; no SP-02 porewater threshold anomaly | Rerun after review fix (hold at 240 s): SP-02 porewater 54.7 PSU at ~230 s, then 57.9-58.2 PSU throughout the hold (sampled peak 58.2). Early warning at ~306 s (KSL-E4, stress 0.537) and ~310 s (KSL-E3, stress 0.541), vegetation 0.0: alerts "KSL-E4: Sub-canopy stress — not yet visible from orbit" and "KSL-E3: …", tasks with trigger `early_warning` in both zones. No SP-02 porewater threshold anomaly during the run. SP-02 anomalies seen: soil moisture spikes (salt scenario) and one porewater spike (58 to 50 PSU) when the hold was cleared at 540 s; both were coalesced into the KSL-E3 early-warning task. First run (override at 360 s, before the fix): early warning fired from the salt alone, and a 60.2 PSU threshold anomaly followed 20 s later. Both runs used an isolated `bcs-gs devstack --test-mode` stack (rules-only AI), because early warning needs a measured vegetation stressor and only the test routes can seed a baseline without the camera. On the launcher stack (no captures) the same salt run left vegetation unmeasured, so no early warning, as designed | Pass (seeded canopy) |
| Full suite: `uv run pytest -q && pnpm -r test && pnpm --filter @bcs/e2e exec playwright test` | All green | pytest 781 passed (10 deselected); `pnpm -r test` green (mission-control 106, sim-console 4, ui 3); Playwright 31 passed, 1 skipped (Mapbox globe, needs a real token); no reruns needed | Pass |

Fixed during the run: the early-warning alert text now carries the spec wording (it read "sub-canopy stress, not yet visible from orbit"); `early-warning-salt.yaml` salted B2-B4, which reach no SP-02, and forced 75 PSU (past the 60 PSU critical band) — it now salts E3/E4 and holds SP-02 at 58 PSU from 240 s (review fix round 1: the original 360 s drift override came after salt alone had passed 60 PSU, and a drift override decays back to that natural value within a minute).

Observed, not fixed:
- Clearing the 58 PSU hold at 540 s drops SP-02 to the recovering natural value (~50 PSU), which raises a porewater spike anomaly. That happens after the early warning, in the recovery phase.
- Gemma's narratives on healthy zones called 25.7 PSU and 17 NTU "high" while every stressor was 0.0. Code numbers stay authoritative, but the wording is alarmist.
- Connection errors put no key or model into cooldown (only 429, 503 and timeouts do), so each offline call spends ~4.4 s on two failing Gemini attempts before Gemma. That is within the 60 s budget.

Still open for the next hardware session:
- [ ] Real-camera flag (remove a plant, exposure locked, baseline set): Gemini vision narrative with chip "Gemini 2.5 Flash" within 10 s, confidence bars, `ai_calls` attempts.
- [ ] Wi-Fi or internet physically off, flag again: chip "Gemma 4 · local" or "Rules", one `ai_degraded` alert per role; reconnect and Gemini answers again after the cooldown.
- [ ] Early warning on the launcher stack with a real camera baseline (Console, "Salt intrusion" on E3).
- [ ] Visual check, with a real Mapbox token, of the Digital Twin 3D layers, the Command Center and the Satellite Intelligence AI panels.

## Time Travel (M5)

Run 2026-10-13 (M5 Task 9) without the camera (ruling R14). A throw-away `bcs-gs devstack --test-mode` stack on ports 8720/8721 (rules-tier parameters, seeded numbers-only baseline and a flagged KSL-B3: 15 pp canopy loss, 30 % mud) stood in for the real capture; the normal stack on 8700/8701 was not touched.

| Check | Expected | Measured (2026-10-13) | Result |
|-------|----------|-----------------------|--------|
| `POST /forecasts` (no plan) | `forecast.ready`, tiers and `confidence_prediction` stored | ready in 0.5 s wall (`elapsed_ms` 239); 25 zones all tier `rules` (test mode); `confidence_prediction` 0.5048; years 2026-2035 | Pass |
| Media | 20 textures + 20 heights under `/media/futures` | 20 + 20 served (10 years x 2 scenarios), also for the applied-plan forecast; rendered lazily on the first 404 (ruling R22b) | Pass |
| Propose plan, edit one zone (PUT), apply | Versions 1 draft, 2 and 3 `mixed`, applied, new forecast | v1 (AI, empty in test mode: rules planner proposes no zones); PUT KSL-B3 plant_avicennia 400 then plant_rhizophora 600 gave v2 and v3 (`mixed`, no warnings); apply gave a new forecast, ready in 0.5 s | Pass |
| "With" vs "without" at 2035 (site) | "With" improves | canopy central 52.1 % without vs 53.6 % with (low/high 31.2/67.8 vs 32.3/69.4); stock 51,330 vs 52,747 tCO2e; additional 0.0 vs 34.3 tCO2e (25.7-42.9); risk class low in both | Pass |
| Illustrations (4 rows) | Terminal rows | all 4 `failed`: "unavailable: test mode never calls NVIDIA" (no NVIDIA in test mode); the code-only repaint is the working path | Pass (code-only) |
| Full suite | All green | pytest 902 passed (11 deselected); mission-control 139, sim-console 4, ui 3; Playwright 37 passed, 1 skipped (Mapbox globe, needs a real token) with `E2E_GS_PORT=8710 E2E_SIM_PORT=8711` | Pass |

NVIDIA FLUX finding (live check, `services/ground-station/tests/live/test_live_flux.py -m live`): the edit call is refused in 1.3 s with HTTP 422 `Expected: example_id, got: base64`. The hosted `flux.2-klein-4b` endpoint accepts only NVIDIA example images for editing with this key, so our base64 site image is rejected. Illustrations therefore end `failed` (one call per 30 min, then the failure is sticky, ruling R25) and Time Travel uses the code-only repaint; no "AI-illustrated" badge appears. The M5 exit check (AI-illustrated keyframes when available, code-only otherwise) is met through the code-only path only.

Notes: `pnpm -r test` also runs the e2e package, which reuses a stack already on 8700 (the normal stack, which has no test routes, so 17 e2e tests failed there); run Playwright with the alternate ports as above.

Still open for the next hardware session (PENDING):
- [ ] PENDING: forecast from a real capture (both maps start from the latest real capture; slider and bands update).
- [ ] PENDING: 3D visual check of canopy thinning and browning, erosion and water colour, with a real Mapbox token, on the real capture.
- [ ] PENDING: saplings visible and growing on the "with" map for the real site; Propose plan (AI) with a real Gemini plan on real zones.
- [ ] PENDING: 4 illustration rows `ready` within about 60 s with "AI-illustrated" on 2030 and 2035 (blocked by the FLUX 422 above until a key or endpoint that accepts base64 edits is available).

## Ledger (M6)

Run 2026-10-13 (M6 Task 9) without the camera (ruling R5): the real-camera Verified loop needs a hands-on session (camera plugged in, plant cuttings), so it is PENDING below. The automated checks ran against test data and a test-mode stack on ports 8710/8711; the normal stack on 8700/8701 and the real ledger database were not touched.

Expected lines for the hardware session:
- Projected record from a real applied plan (the checklist must be all ✓).
- 3 recovery captures after adding real green plant cuttings to the planted zone.
- 2 healthy minutes on the sensors.
- Confidence ≥ 0.80 (exposure locked).
- A Verified record appears automatically, with its evidence pack.
- "Verify chain" in the live app shows "intact".

| Check | Expected | Measured (2026-10-13) | Result |
|-------|----------|-----------------------|--------|
| Tamper test: `uv run pytest services/ground-station/tests/seam1/test_ledger.py -k tamper -v` | Broken link at the tampered index, `chain_broken` alert, issuance blocked | `test_tamper_detected_at_index_and_blocks_issuance` 1 passed, 8 deselected (3.7 s) | Pass |
| Live "Verify chain" on a test-mode Ground Station (`E2E_GS_PORT=8710 E2E_SIM_PORT=8711 playwright test ledger.spec.ts`): seeds a Projected record (seeded test data, not created from a real applied plan), presses Verify chain | "intact" | 3 passed (29.8 s): generate Projected then Verify chain shows intact; evidence pack downloads as PDF; eligibility tracker shows the four rules and the demo disclaimer | Pass (test-mode stack) |
| Verified gating on all four rules: `services/ground-station/tests/seam1/test_eligibility.py::test_verified_issued_only_when_all_four_rules_pass` (automated, manual clock) | Verified issued only when all four rules pass | Covered by the automated test in the full pytest run (passed) | Pass (automated) |
| Full suite: pytest, `pnpm -r --filter "!@bcs/e2e" test`, `pnpm build`, Playwright | All green | pytest 979 passed, 11 deselected, 1 failed on the first run (`simulator/tests/seam1/test_runtime.py::test_runtime_publishes_telemetry_for_every_registered_node`); that file alone: 7 passed. Unit packages: mission-control 161, sim-console 4, ui 3, all passed. `pnpm build` succeeded. Playwright 40 passed, 1 skipped (Mapbox globe, needs a real token), 2 failed on the full run (`console.spec.ts` fault toggle, `time-travel.spec.ts` slider scrubbing); those two files alone: 14 passed | Not green in a single full run: pytest `test_runtime_publishes_telemetry_for_every_registered_node` failed once and passed when its file was rerun alone (7 passed); Playwright `console.spec.ts` fault toggle and `time-travel.spec.ts` slider scrubbing failed in the full run and passed when rerun alone (14 passed); the time-travel failure is a newly observed intermittent |

Still open for the next hardware session (PENDING):
- [ ] PENDING: Projected record from a real applied plan.
- [ ] PENDING: 3 recovery captures with real plant cuttings in the planted zone.
- [ ] PENDING: 2 healthy sensor minutes.
- [ ] PENDING: confidence ≥ 0.80 with exposure locked.
- [ ] PENDING: automatic Verified record with its evidence pack.
- [ ] PENDING: "Verify chain" pressed in the live app on the normal stack shows "intact".
- [ ] PENDING: visual check with a real Mapbox token of the planned-site globe markers, the fly-in (Fly to Kuala Selangor) and the 3D carbon columns.

## Results

| Date | Stream fps (SVGA / XGA) | Surface rate (fps) | Server latency (ms) | Browser receive → upload (ms) | Frame to screen (ms) | Pass/Fail | Notes |
|------|-------------------------|--------------------|---------------------|-------------------------------|----------------------|-----------|-------|
| 2026-10-09 | 4.6 / — | — | — | — | — | Partial | Section 0 bring-up on the real board: USB flash, portal, Wi-Fi join, `/status` = `CAM-01`, 401 without token, 200 with token, second `/stream` client 503 all pass. Joined only after fix 6fb60d8 (full TX power on connect). Stream 4.6 fps over a phone hotspot (~67 ms RTT); router link at -66 dBm had 30 % ping loss. Remaining items carried to the next hardware session. |
