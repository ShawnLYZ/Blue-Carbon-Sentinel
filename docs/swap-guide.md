# Swap guide

Three seams let real components replace the demo ones without changing the rest of the system. Each swap
is confined to the named interface and its configuration; a new AI provider also needs a few lines of
registration code (section 2).

## 1. Real Sentinel Nodes replace the simulator

The Sentinel Protocol ([protocol/sentinel-protocol-v1.md](protocol/sentinel-protocol-v1.md); addendum Part G)
is the node seam. A real node is a node whose firmware speaks it.

1. **Register it as hardware.** In Mission Control, Sentinel Network, add a node and choose the hardware
   source, or call the API: `POST /api/v1/nodes` with `{"node_type": "water_quality" | "soil_probe" |
   "tide_gauge", "source": "hardware", "position": {...}}`. The response carries the node ID (for example
   `WQ-01`) and its device key.
2. **Flash the key.** The key is shown once and only a hash is stored. Put it in the firmware as the MQTT
   password. If it is lost, regenerate it (`POST /api/v1/nodes/{node_id}/regenerate-key`, or the device
   registry on the System page) and reflash. Never commit a key.
3. **Connect as the node.** MQTT v5, QoS 1, keep-alive 30 s, `clean_start = false`, client ID = user name =
   node ID, password = the device key, to the broker on port 1883 of the Ground Station machine.
4. **Speak Part G.**
   - Publish to `bcs/v1/{site_id}/nodes/{node_id}/{channel}` for `telemetry`, `event`, `status` (retained,
     with a retained last will `state: "offline"`, `reason: "last_will"`) and `ack`.
   - Subscribe to your own `cmd` and `config` (the latter retained). Acknowledge every command with an
     `ack` carrying its `command_id`.
   - Validate payloads against `packages/protocol/schemas/*.schema.json`; readings outside the physical
     ranges in section 4 of the protocol make the message malformed and it is dropped with a node event.
   - Follow the edge-logic reference (section 9): boot ID, per-boot `seq` counters, rolling-window spike,
     threshold and stuck detection, battery flag, and the sampling intervals of the timing table.
5. **Check.** The node appears in Sentinel Network, turns online on its first status or telemetry message,
   and the Ground Station applies the same ingest rules (validate, dedupe, order, late flag) as for a
   simulated node. The broker ACL denies everything except the node's own topics.

The simulator keeps working beside real nodes; remove simulated ones with decommission when no longer needed.

## 2. Trained models replace an AI role

Every AI role (`vision_analyst`, `tree_locator`, `risk_interpreter`, `forecast_parameter_estimator`,
`restoration_planner`, `history_synthesizer`) is called through the AI gateway (`bcs_gs/ai/gateway.py`),
which tries a chain of tiers in order and always ends on the deterministic rules tier. A trained model is
one more provider in that chain.

**Build a dataset from the AI call log.** Every attempt is stored in `ai_calls` with its role, tier, model,
prompt and schema versions, inputs, image references and output. Export it as JSON Lines:

    curl "http://127.0.0.1:8700/api/v1/ai/calls/export?role=risk_interpreter&status=success&limit=1000" > risk.jsonl

Filters: `role`, `tier`, `status`, `from`, `to` (ISO times) and `limit` (1 to 1000). Output is oldest
first, one attempt per line, with the columns listed in `bcs_gs/ai/export.py` (`inputs`, `output`, `valid`,
`latency_ms`, `fallback_from`, ...). Key values are never stored, only the key slot, and secrets are masked.
Keep rows where `valid` is true as supervised pairs (inputs to output), resolve `image_refs` to the stored
captures, and treat `rules` rows as a baseline rather than as labels. Operator-edited plans and the ledger
give the corrections.

**Implement an `AIProvider`** (`bcs_gs/ai/providers/base.py`):

    class AIProvider(Protocol):
        provider: str          # "gemini" | "ollama" | "rules" | "fake" | a future "trained"
        async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict: ...

`ProviderRequest` carries `role`, `system`, `parts` (text or JPEG bytes up to 1024 px), `response_schema`
(the role's JSON Schema), `temperature` and `timeout_s`. Return a dict that validates against the schema,
and raise `ProviderError(kind)` with a kind from `rate_limited`, `overloaded`, `timeout`, `unavailable`,
`invalid_output` or `error`; the gateway then falls back to the next tier. Never put key values in error
detail.

**Register it in `select_ai_providers`** (`bcs_gs/api/app.py`). This is a small code change, not
configuration: add the instance to the returned dict under its provider name (for example
`providers["trained"] = TrainedProvider(...)`), so the gateway can find the provider a tier names. The same
function is the hook the tests use to inject fakes.

**Select it per role in `config/ai.yaml`.** Add a tier and put it in the chain of just the role it
replaces:

    tiers:
      trained_risk: { label: "Trained risk model", provider: trained, factor: 0.92 }
    models:
      trained_risk: risk-v1
    chains:
      risk_interpreter: [trained_risk, gemini_primary, gemma_local, rules]

`factor` is the prediction-confidence factor of the answering tier (methodology section 4); choose it from
a held-out evaluation, not by hand. Roles you do not touch keep their chains. The rules tier is always
last. A role with no reachable provider is answered by rules, and the UI shows the source chip of whichever
tier answered.

## 3. Sentinel-2 replaces the ESP32-CAM through `ImagerySource`

Imagery is consumed through one interface (`bcs_gs/camera/imagery.py`):

    class ImagerySource(Protocol):
        source_id: str
        def online(self) -> bool: ...
        def latest(self) -> SiteRaster | None: ...
        def recent(self, n: int) -> list[SiteRaster]: ...
        def subscribe(self) -> AsyncIterator[SiteRaster]: ...

`SiteRaster` is a north-up 512 x 512 raster: `image` (uint8, shape `512 x 512 x len(bands)`), `bands`,
`captured_at` (UTC), `source_id`, `seq` and `calibration_id`. The camera source produces
`bands = ("R", "G", "B")`. A Sentinel-2 source produces `bands = ("B2", "B3", "B4", "B8")` (blue, green,
red, near infrared, all 10 m bands), resampled to the site raster.

**True NDVI.** With a B8 band the vegetation index is no longer a proxy:

    NDVI = (B8 - B4) / (B8 + B4)        # nir = B8, red = B4, as reflectance, clamped to [-1, 1]

A Sentinel-2 source should supply surface reflectance (Level-2A scaled by 1/10000), not raw digital
numbers. Replace the VARI computation (`vari` in `bcs_gs/vegetation/indices.py`) with this formula when `"B8" in bands`, drop the
"NDVI proxy" label for those rasters, and revisit the canopy thresholds and the baseline-relative stressor
scaling, which are tuned on a tank camera (methodology sections 1 and 7). Cloud cover, revisit time
(about 5 days) and the 10 m pixel (a 100 m zone is 10 x 10 pixels) replace the live-camera assumptions:
captures are no longer continuous, the exposure lock does not apply, and the camera-confidence recency
factor should be reconsidered.

Wire the new source where `CameraImagerySource` is constructed (`bcs_gs/api/app.py`) and keep the interface unchanged;
classification, metrics, fusion, forecast and ledger read only `SiteRaster`.
