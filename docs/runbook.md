# Demo runbook

For the operator at the booth. Commands are Windows PowerShell 5.1 from the repository root. Never read
secret values aloud or show them on screen: refer to variables by name (`.env.example` lists them).

## 1. Before you leave (the night before)

1. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1` (safe to repeat; it also fetches
   the depth model, about 250 MB, once).
2. `scripts\start.ps1`, read the preflight summary, fix every red line using section 6, then
   `scripts\perf.ps1 -Seconds 120` once and keep the table.
3. Confirm Supabase is active (section 7) and that the camera boots on the hotspot you will use.
4. Charge the laptop and bring its charger. Do not update dependencies at the venue.

## 2. Booth setup

**Network.** The camera, laptop and phone must share one network.

- Use a phone hotspot on **2.4 GHz**. The ESP32-CAM cannot join 5 GHz. On an iPhone turn on Settings >
  Personal Hotspot > **Maximize Compatibility**; on Android choose the 2.4 GHz band.
- The camera is configured through its captive portal (`SentinelCam-Setup`; section 0 of the
  [manual camera checklist](manual-camera-checklist.md)). Join the portal from a phone, choose the hotspot, and the
  camera appears as `sentinel-cam.local` (`BCS_CAMERA_HOST`). Venue Wi-Fi with client isolation blocks it.
- The Ground Station API binds to localhost; nothing needs to reach the laptop from outside.

**Chrome on the high-performance GPU.** Mission Control renders 3D and needs the RTX GPU. In Windows Settings >
System > Display > Graphics add `chrome.exe`, open Options and choose **High performance** (the
**high-performance GPU**). Restart Chrome and check that `chrome://gpu` lists the NVIDIA adapter. Keep the laptop
plugged in.

**Windows Firewall prompt for Mosquitto.** The first time the broker starts, Windows asks whether to allow
`mosquitto.exe`. Allow it on Private networks, otherwise MQTT clients on other devices cannot connect (simulated
nodes on the same laptop still do, which can hide the problem).

**Stop the Mosquitto Windows service.** The service installed with Mosquitto starts on boot and holds port 1883.
In an administrator shell run `net stop mosquitto` and set its startup type to Disabled (`services.msc` >
Mosquitto Broker). Otherwise the launcher and preflight report that another process holds port 1883.

**Tank and camera.** Mount the camera top-down over the tank in even light with no flicker (no direct sun, no
mains-flicker lamps). Do not move it after calibration.

## 3. Calibration, exposure lock and commissioning

1. **Start:** `scripts\start.ps1`. It opens Mission Control (`/`) and the Simulator Console (`/console/`) as Chrome
   app windows on `http://127.0.0.1:8700`.
2. **Exposure lock.** On the System page, Camera section, lock exposure and white balance and wait for "Exposure / WB:
   locked (confirmed by the camera)". An unlocked capture is tagged, still analysed, and lowers camera confidence
   (x 0.85). Relock whenever the light changes.
3. **Calibration.** On the Satellite Intelligence page pick the **four corners** of the tank in the live view and
   mark the **north edge**. The default calibration is only an approximation (confidence factor 0.9 against 1.0 for
   four corners). Reset it from the System page if the camera moves.
4. **Baseline.** With healthy plants and final light, set the baseline capture on Satellite Intelligence. Dieback,
   growth and vegetation stress are measured against it.
5. **Commissioning.** System page > Commissioning places the nodes from the latest capture's class map (water, mud,
   shore), or spreads them evenly when no usable capture exists (low confidence). Re-run it after recalibrating.
   Check the coverage panel on Sentinel Network: every zone should be covered by a water-quality or soil node,
   otherwise the Verified rule fails with "no coverage".

## 4. Demo Director script (about 5 minutes)

Press `d` in Mission Control to open the **Demo Director** panel and start it. It is a server state machine driven
only by real events: a step completes when its trigger happens, not when time passes. Skip, Retry and Exit are in
the panel. Demo time (on by default) compresses sampling and verification windows (investigation sampling every 2 s,
tasks last 3 min, the Verified sensor window is 2 min, a capture every 10 s). Do not change the demo time scale
mid-demo.

| Time | Step | Say and do |
|---|---|---|
| 0:00 | Intro | Command Center: the tank is a mangrove site watched by a camera, sensor nodes, AI and a ledger. "Code measures, AI interprets." |
| 0:30 | Early warning (optional) | In the Simulator Console apply a sensor scenario (for example Salt intrusion) to a zone before touching the tree. An early-warning alert fires from sensors alone. Skip this branch when short on time. |
| 1:00 | 1 Detect | Brown or remove a tree. Once the scene settles (about 5 s) the capture flags the zone on Satellite Intelligence. |
| 1:30 | 2 Task | The Ground Station tasks nearby nodes into investigation mode (show Sentinel Network). Advances on the first acknowledgement. |
| 2:00 | 3 Measure | In the Simulator Console apply a scenario to that zone (Sediment runoff, Low oxygen, ...). Advances after 5 investigation samples. |
| 2:45 | 4 Fuse | Digital Twin zone card: risk score and class, stressors, confidence, and the AI narrative with its source chip. |
| 3:15 | 5 Predict | Time Travel opens. Run forecast, then scrub to 2035 and compare with and without the plan; keyframe illustrations arrive asynchronously. |
| 3:45 | 6 Restore | Propose or edit the plan, apply it, then plant the clay saplings. Advances when a capture detects new growth. |
| 4:30 | 7 Verify | Carbon Ledger: generate the Projected record, show the eligibility tracker and the automatic Verified record, verify the chain, open the evidence pack. Close with "Demo record, not a certified credit". |
| 5:00 | End | Exit the Director. |

When a step is blocked the panel says so, for example **Camera offline - step requires live captures**. Fix the
cause (section 6) and press Retry, or Skip. The Director never fabricates an event, so do not simulate one.

## 5. During the demo

- The System page has Cloud and Versions sections. A **"Buffering offline (n queued)"** badge means the cloud is
  unreachable or paused (three failed sync passes in a row): the demo continues from the local store and syncs later
  (section 7). The Cloud sync chip reads "Buffering" while rows simply wait to be sent; that is normal.
- A new machine, or one with a wiped `var\` folder, starts with an empty store. With the cloud configured the Ground
  Station **hydrates** itself at start: the last 24 h of telemetry and alerts, sites, plans, forecasts, the ledger
  (chain re-verified), the baseline and the referenced captures.
- **Fresh or backup laptop: hydrate first.** Run `uv run bcs-gs hydrate` **before** `scripts\start.ps1`. Pulling the
  media can take longer than the launcher's 60 s readiness wait; done by hand it prints each table's count and the
  chain result, and the launcher then starts on a complete store. The command refuses while a Ground Station
  answers on port 8700 (run `scripts\stop.ps1` first), and on a store that already has history unless you pass
  `--force`. When the Ground Station hydrates at start instead, `var\logs\gs.err.log` shows "hydrating from
  cloud..." and then "hydration finished in N s".
- **Hydrated nodes come back by themselves.** Node keys are never pulled from the cloud. At start the Ground
  Station issues fresh keys and broker accounts to the hydrated simulated nodes and the simulator picks them up, so
  they turn online with no manual step. A hardware node needs **Regenerate key** (System page, device registry)
  and a re-flash.
- `scripts\stop.ps1` stops everything the launcher started.

## 6. Recovery per preflight check

Preflight runs at start and can be re-run from the System page (`POST /api/v1/system/preflight`). The eleven
checks, in order:

| Check | Meaning when it fails or warns | Recovery |
|---|---|---|
| `camera` | `sentinel-cam.local` did not resolve, or its `/status` did not answer | Power the camera, confirm it joined the 2.4 GHz hotspot, check `BCS_CAMERA_HOST` and `BCS_CAMERA_IP`. A double reset within 5 s reopens the setup portal. The demo still runs, but steps 1 and 6 need live captures. |
| `broker` | Login as the Ground Station failed, or no password | Set `BCS_GS_MQTT_PASSWORD` in `.env` and start with `scripts\start.ps1`; if it persists run `uv run bcs-gs broker-init`. |
| `broker_port` | Another process holds port 1883 (fail), or nothing listens (warn) | Stop and disable the Windows Mosquitto service (section 2), then start again. |
| `supabase` | Credentials missing, state unreadable, or the project is paused | Section 7. Work is buffered locally meanwhile. |
| `cloud_usage` | Database near or over the 500 MB free-tier limit | Prune data in the dashboard. |
| `gemini_keys` | Fewer than 3 keys work | Check the named `BCS_GEMINI_API_KEY_n` variables. With none, the rules tier answers (confidence factor 0.75). |
| `nvidia_key` | Missing or rejected | Check `BCS_NVIDIA_API_KEY`; Time Travel keyframes fall back to the code-only repaint. |
| `mapbox_token` | Missing or rejected | Set `BCS_MAPBOX_PUBLIC_TOKEN` (a `pk.` token) and check its URL restrictions allow `http://127.0.0.1:8700` (section 8). |
| `depth_model` | No model, or DirectML unavailable | `uv run bcs-gs fetch-models`; update the GPU driver; `uv sync` for `onnxruntime-directml`. |
| `ollama` | Not running, or the Gemma model not pulled | Start Ollama and `ollama pull gemma4:e4b` (the model named in `config/ai.yaml`). The tier is optional. |
| `disk` | Under the recommended 5 GB free | Free disk space. |

Other failures: blank Chrome windows mean the web build is missing (`pnpm build`); logs are in `var\logs`
(`gs.err.log`, `sim.err.log`, `mosquitto.err.log`).

## 7. Supabase

The project ref is the part of `BCS_SUPABASE_URL` before `.supabase.co`; the dashboard is
`https://supabase.com/dashboard/project/<project-ref>`.

- **Unpausing.** Free-tier projects pause after inactivity. Open the dashboard and restore the project (it takes a
  few minutes). Preflight `supabase` then passes and the queued work syncs.
- **Pending migrations.** Push them with the Supabase CLI; Docker is not needed:
  `supabase link --project-ref <project-ref>`, then `supabase db push --yes`. `scripts\setup.ps1` does both
  and needs `BCS_SUPABASE_URL` and `SUPABASE_DB_PASSWORD` in `.env`; `SUPABASE_ACCESS_TOKEN` lets preflight read
  the project state. Migrations live in `supabase\migrations`.
- Cloud tests (`pytest -m cloud`) hit this project; run them only locally.

## 8. Key rotation before the repository is made public (design section 34)

All keys were held in a plain-text local key file (`API_Key_Configuration.md`, gitignored and not in the repository)
and appeared in the planning conversation. **Key rotation** is required before the repository is ever made public:

1. **Supabase service-role key** (`BCS_SUPABASE_SERVICE_ROLE_KEY`): dashboard > Project Settings > API, roll the keys.
   Rolling the JWT secret also invalidates the anon key, so update `BCS_SUPABASE_ANON_KEY` too.
2. **Supabase database password** (`SUPABASE_DB_PASSWORD`): dashboard > Project Settings > Database > reset password.
3. **Gemini keys** (`BCS_GEMINI_API_KEY_1` to `_3`): create new keys in Google AI Studio, then delete the old ones.
4. **NVIDIA key** (`BCS_NVIDIA_API_KEY`): create a new key in the NVIDIA API catalogue, then revoke the old one.
5. Also rotate, if they were ever shared: `SUPABASE_ACCESS_TOKEN`, the camera token and OTA password
   (`BCS_CAMERA_TOKEN`, `BCS_CAMERA_OTA_PASSWORD`; then reflash with `scripts\fw.ps1 upload`), the broker passwords
   (`BCS_BROKER_ADMIN_PASSWORD`, `BCS_GS_MQTT_PASSWORD`) and `BCS_SIM_SHARED_TOKEN`.
6. Put the new values in `.env` only. Search the git history for leaked values before changing the repository's
   visibility, and delete `API_Key_Configuration.md` once the rotation is done.
7. **Mapbox:** `BCS_MAPBOX_PUBLIC_TOKEN` is the one key allowed in the browser. Before any public hosting add **URL
   restrictions** to it (Mapbox account > Access tokens > URL restrictions) listing only the origins that serve
   Mission Control.
8. Restart with `scripts\start.ps1`; preflight must pass for every rotated key.
