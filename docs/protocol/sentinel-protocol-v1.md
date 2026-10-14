# Sentinel Protocol v1

The message contract between Sentinel Nodes (hardware or simulated) and the Ground Station. The
JSON Schemas in `packages/protocol/schemas/` are the machine-readable source of truth; this
document is the prose. Every example below is checked by
`services/ground-station/tests/contract/test_protocol_doc_examples.py`.

## 1. Transport

| Item | Value |
|---|---|
| Protocol | MQTT v5 |
| QoS | 1 for every channel |
| Keep-alive | 30 s |
| Session | `clean_start = false`, session expiry 3,600 s, so QoS 1 commands survive short disconnects |
| Max in-flight | 20 |
| Retained | `status` and `config` only |
| Last will | Retained `status` message with `state: "offline"` and `reason: "last_will"`, will delay 0 |
| Identity | Client ID = user name = node ID |
| Topic | `bcs/v1/{site_id}/nodes/{node_id}/{channel}`, channel one of `telemetry`, `event`, `status`, `ack`, `cmd`, `config` |

Schema files live in `packages/protocol/schemas/` (`telemetry`, `status`, `event`, `cmd`, `ack`,
`config`, plus `common.schema.json`), JSON Schema draft 2020-12, with `additionalProperties: false`
everywhere except the `details`, `params` and `config` objects.

## 2. Fields common to node to Ground Station messages

| Field | Type | Rule |
|---|---|---|
| `schema` | string | Constant per message type: `bcs.telemetry.v1`, `bcs.status.v1`, `bcs.event.v1` or `bcs.ack.v1` |
| `site_id` | string | `^[A-Z]{3}$`; must equal the topic's site |
| `node_id` | string | `^(WQ\|SP\|TG)-\d{2,3}$`; must equal the topic's node |
| `source` | string | `simulated` or `hardware` |
| `replay` | boolean | `true` only for simulator replays (a replay must have `source: "simulated"`) |

## 3. Messages

### Telemetry `bcs.telemetry.v1`

Node to Ground Station; not retained.

| Field | Type | Rule |
|---|---|---|
| `node_type` | string | Must match the node's registry type |
| `boot_id` | string | `^[0-9a-f]{12}$` |
| `seq` | integer | 0 or more; strictly increasing per boot |
| `sampled_at` | string | UTC ISO 8601 with milliseconds |
| `mode` | string | `baseline` or `investigation` |
| `readings` | object | Exactly the keys for the node type (section 4) |
| `health` | object | `battery_pct` (0-100), `rssi_dbm` (-120 to 0), `uptime_s` (0 or more), `fw_version` (string, at most 32 characters) |
| `flags` | array | Items `{parameter, kind, score}`; `parameter` is a reading key or `battery_pct`, `kind` is an edge flag kind, `score` is a number |

<!-- example:telemetry:valid -->
```json
{
  "schema": "bcs.telemetry.v1",
  "site_id": "KSL",
  "node_id": "WQ-02",
  "node_type": "water_quality",
  "boot_id": "9f2c41ab07de",
  "seq": 418,
  "sampled_at": "2026-10-16T03:04:05.123Z",
  "mode": "investigation",
  "readings": { "salinity_psu": 27.4, "turbidity_ntu": 162.8, "do_mg_l": 4.12, "temp_c": 30.45, "ph": 7.62 },
  "health": { "battery_pct": 86.5, "rssi_dbm": -63, "uptime_s": 5412, "fw_version": "sim-1.0.0" },
  "flags": [ { "parameter": "turbidity_ntu", "kind": "threshold", "score": 1.0 } ],
  "source": "simulated",
  "replay": false
}
```

Broken: `ph` is 14.5, outside the physical range 0-14, so the message is malformed.

<!-- example:telemetry:invalid -->
```json
{
  "schema": "bcs.telemetry.v1",
  "site_id": "KSL",
  "node_id": "WQ-02",
  "node_type": "water_quality",
  "boot_id": "9f2c41ab07de",
  "seq": 419,
  "sampled_at": "2026-10-16T03:04:07.123Z",
  "mode": "baseline",
  "readings": { "salinity_psu": 27.4, "turbidity_ntu": 162.8, "do_mg_l": 4.12, "temp_c": 30.45, "ph": 14.5 },
  "health": { "battery_pct": 86.5, "rssi_dbm": -63, "uptime_s": 5414, "fw_version": "sim-1.0.0" },
  "flags": [],
  "source": "simulated",
  "replay": false
}
```

### Status `bcs.status.v1`

Node to Ground Station; **retained**; also the last will.

| Field | Type | Rule |
|---|---|---|
| `state` | string | `online` or `offline` |
| `at` | string | Time of the status. For a last will this is the connect time; the Ground Station uses its receive time instead. |
| `reason` | string or null | `last_will`, `shutdown` or null |
| `mode` | string or null | null when offline |
| `interval_s` | number or null | Current sampling interval |
| `fw_version` | string | |
| `boot_id` | string | |

<!-- example:status:valid -->
```json
{
  "schema": "bcs.status.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "state": "offline",
  "at": "2026-10-16T03:00:00.000Z",
  "reason": "last_will",
  "mode": null,
  "interval_s": null,
  "fw_version": "sim-1.0.0",
  "boot_id": "9f2c41ab07de",
  "source": "simulated",
  "replay": false
}
```

Broken: an offline node must have `mode: null`.

<!-- example:status:invalid -->
```json
{
  "schema": "bcs.status.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "state": "offline",
  "at": "2026-10-16T03:00:00.000Z",
  "reason": "last_will",
  "mode": "baseline",
  "interval_s": null,
  "fw_version": "sim-1.0.0",
  "boot_id": "9f2c41ab07de",
  "source": "simulated",
  "replay": false
}
```

### Event `bcs.event.v1`

Node to Ground Station; not retained.

| Field | Type | Rule |
|---|---|---|
| `boot_id`, `seq` | string, integer | `seq` is the event's own per-boot counter, independent of telemetry `seq`. Both counters restart at 0 on boot. The Ground Station dedupes telemetry and events each on (node, boot, seq). |
| `at` | string | |
| `kind` | string | `anomaly`, `threshold`, `stuck`, `battery_low`, `boot`, `config_applied` or `malformed_input` |
| `parameter` | string or null | |
| `value`, `score` | number or null | |
| `details` | object | Free-form, at most 2 KB when serialised |

<!-- example:event:valid -->
```json
{
  "schema": "bcs.event.v1",
  "site_id": "KSL",
  "node_id": "WQ-02",
  "boot_id": "9f2c41ab07de",
  "seq": 3,
  "at": "2026-10-16T03:04:05.123Z",
  "kind": "anomaly",
  "parameter": "turbidity_ntu",
  "value": 162.8,
  "score": 4.2,
  "details": { "window": 30 },
  "source": "simulated",
  "replay": false
}
```

Broken: `seq` must be an integer.

<!-- example:event:invalid -->
```json
{
  "schema": "bcs.event.v1",
  "site_id": "KSL",
  "node_id": "WQ-02",
  "boot_id": "9f2c41ab07de",
  "seq": 3.5,
  "at": "2026-10-16T03:04:05.123Z",
  "kind": "anomaly",
  "parameter": "turbidity_ntu",
  "value": 162.8,
  "score": 4.2,
  "details": { "window": 30 },
  "source": "simulated",
  "replay": false
}
```

### Ack `bcs.ack.v1`

Node to Ground Station; not retained.

| Field | Type | Rule |
|---|---|---|
| `command_id` | string | UUID of the command |
| `at` | string | |
| `status` | string | `accepted`, `rejected`, `completed` or `expired` |
| `reason` | string or null | |

<!-- example:ack:valid -->
```json
{
  "schema": "bcs.ack.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
  "at": "2026-10-16T03:00:01.000Z",
  "status": "accepted",
  "reason": null,
  "source": "simulated",
  "replay": false
}
```

Broken: `status` must be one of the four listed values.

<!-- example:ack:invalid -->
```json
{
  "schema": "bcs.ack.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
  "at": "2026-10-16T03:00:01.000Z",
  "status": "maybe",
  "reason": null,
  "source": "simulated",
  "replay": false
}
```

### Command `bcs.cmd.v1`

Ground Station to node; not retained.

| Field | Type | Rule |
|---|---|---|
| `schema`, `site_id`, `node_id` | | As in section 2 |
| `command_id` | string | UUIDv7 |
| `type` | string | `set_mode`, `set_config`, `ping` or `reboot` |
| `params` | object | `set_mode`: `{mode, duration_s, interval_s?}` with `duration_s` required for investigation. `set_config`: a partial config. `ping` and `reboot`: `{}`. |
| `issued_at`, `expires_at` | string | A node rejects commands it receives after `expires_at` with status `expired`. |
| `task_id` | string or null | |
| `reason` | string | At most 200 characters |

<!-- example:cmd:valid -->
```json
{
  "schema": "bcs.cmd.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
  "type": "set_mode",
  "params": { "mode": "investigation", "duration_s": 120 },
  "issued_at": "2026-10-16T03:00:00.000Z",
  "expires_at": "2026-10-16T03:00:30.000Z",
  "task_id": null,
  "reason": "turbidity anomaly in zone B3"
}
```

Broken: `set_mode` to `investigation` requires `duration_s`.

<!-- example:cmd:invalid -->
```json
{
  "schema": "bcs.cmd.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
  "type": "set_mode",
  "params": { "mode": "investigation" },
  "issued_at": "2026-10-16T03:00:00.000Z",
  "expires_at": "2026-10-16T03:00:30.000Z",
  "task_id": null,
  "reason": "turbidity anomaly in zone B3"
}
```

### Config `bcs.config.v1`

Ground Station to node; **retained**.

| Field | Type | Rule |
|---|---|---|
| `schema`, `site_id`, `node_id` | | As in section 2 |
| `config_version` | integer | Increases on every change |
| `issued_at` | string | |
| `demo_time_scale` | boolean | |
| `baseline_interval_s`, `investigation_interval_s` | integer | 30 / 2 with demo time on; 900 / 30 with it off |
| `anomaly` | object | `{window: 30, z_threshold: 3.0, stuck_window: 10, stuck_epsilon: {<reading>: number}}` |
| `critical_bands` | object | `{<reading>: {min?, max?}}`: thresholds. A reading is critical when value < `min` or value > `max`; a `threshold` flag fires on the first transition from inside to outside. Demo bands: `do_mg_l` {min 2.0}, `ph` {min 6.5, max 9.0}, `turbidity_ntu` {max 100}, `salinity_psu` {max 45}, `porewater_salinity_psu` {max 60}, `temp_c` {max 36} |
| `battery_low_pct` | number | 15 |

The Ground Station republishes the retained config on registration, on a demo-time change, and whenever a node transitions to online or reports a new `boot_id`. The node applies the config, then emits a `config_applied` event carrying `config_version` in `details`.

<!-- example:config:valid -->
```json
{
  "schema": "bcs.config.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "config_version": 2,
  "issued_at": "2026-10-16T03:00:00.000Z",
  "demo_time_scale": true,
  "baseline_interval_s": 30,
  "investigation_interval_s": 2,
  "anomaly": { "window": 30, "z_threshold": 3.0, "stuck_window": 10, "stuck_epsilon": { "ph": 0.005 } },
  "critical_bands": { "do_mg_l": { "min": 2.0 }, "ph": { "min": 6.5, "max": 9.0 } },
  "battery_low_pct": 15
}
```

Broken: `config_version` must be an integer.

<!-- example:config:invalid -->
```json
{
  "schema": "bcs.config.v1",
  "site_id": "KSL",
  "node_id": "WQ-01",
  "config_version": "two",
  "issued_at": "2026-10-16T03:00:00.000Z",
  "demo_time_scale": true,
  "baseline_interval_s": 30,
  "investigation_interval_s": 2,
  "anomaly": { "window": 30, "z_threshold": 3.0, "stuck_window": 10, "stuck_epsilon": { "ph": 0.005 } },
  "critical_bands": {},
  "battery_low_pct": 15
}
```

## 4. Readings per node type and validation ranges

These are **physical validation ranges**, not health bands. A value outside them makes the message malformed.

| Node type | Reading | Range | Resolution |
|---|---|---|---|
| `water_quality` | `salinity_psu` | 0-60 | 0.1 |
| `water_quality` | `turbidity_ntu` | 0-4000 | 0.1 |
| `water_quality` | `do_mg_l` | 0-20 | 0.01 |
| `water_quality` | `temp_c` | 0-45 | 0.01 |
| `water_quality` | `ph` | 0-14 | 0.01 |
| `soil_probe` | `porewater_salinity_psu` | 0-120 | 0.1 |
| `soil_probe` | `soil_moisture_pct` | 0-100 | 0.1 |
| `tide_gauge` | `water_level_cm` | -500 to 500 | 1 |

## 5. Ground Station processing rules

1. Parse JSON.
2. Validate the schema using the generated Pydantic models.
3. Check consistency: the topic's site and node match the payload; the node is registered and not
   decommissioned; `node_type` matches the registry.
4. Check ranges (section 4).
5. Check timestamps: `sampled_at` must be no later than receive time + 60 s.
6. Deduplicate on (node, boot, seq).
7. Store, then publish events.

- **Failure at steps 1-5.** The message is not stored as a reading. It creates a `node_events` row
  (`origin = 'ground_station'`, `kind = 'malformed'`) with an error list and a payload excerpt of at most 2 KB.
- **Late samples** (`sampled_at` older than 2 x the interval of the sample's own `mode` at receipt) are stored with `late = true`.
- **"Latest" views** always use the newest `sampled_at`.
- **Offline detection.** A last-will status, or no telemetry for 3 x the current interval, marks the
  node offline; an `online` status or new telemetry marks it online again; each transition writes a
  Ground Station node event.
- **Acks.** An ack for an unknown `command_id` is logged as a Ground Station event and otherwise
  ignored; a command still `pending` after 5 s is re-sent once; one still unacknowledged when it
  expires becomes `no_ack`.

## 6. Broker identities and access

| Identity | Created by | Role and ACL |
|---|---|---|
| `admin` (from `BCS_BROKER_ADMIN_USER`) | First broker start: the dynamic-security bootstrap | Dynamic-security control topic only. |
| `bcs-gs` | Ground Station at start-up, idempotent | Subscribe `bcs/v1/+/nodes/+/telemetry`, `.../event`, `.../status`, `.../ack`. Publish `bcs/v1/+/nodes/+/cmd` and `.../config`. |
| Each node (e.g. `WQ-01`) | Ground Station on registration | Its own role `node-WQ-01`: publish only to its own `telemetry`, `event`, `status` and `ack` topics; subscribe and receive only its own `cmd` and `config`. |

Client publishing and subscribing are denied by default. If the dynamic-security plugin cannot
load, a generated password file and an ACL file with per-node `pattern` lines are used.

## 7. Authentication and ACLs

- **Identity.** Each node authenticates with client ID = user name = node ID and a per-node password
  (device key). The Ground Station creates the credential and role at registration; the key is shown
  once and only a hash is stored. Simulated nodes receive their keys from the Ground Station
  automatically.
- **Default deny.** Client publishing and subscribing are denied unless a role grants them.
- **Node role** `node-<ID>`: publish to its own `telemetry`, `event`, `status` and `ack` topics only;
  subscribe to (and receive) its own `cmd` and `config` topics only. A node can neither see nor
  impersonate another node, and cannot publish `cmd` or `config`.
- **Ground Station** (`bcs-gs`): subscribe to `telemetry`, `event`, `status`, `ack` of every node;
  publish `cmd` and `config`. **Admin**: the dynamic-security control topic only.
- **Payload checks on top of ACLs.** The Ground Station rejects a message whose payload `site_id` or
  `node_id` differs from the topic, as `malformed` (section 5).
- **Fallback.** Without the dynamic-security plugin: a generated password file plus an ACL file with
  per-node `pattern` lines.
- **Transport security.** The demo broker listens on the local network without TLS. A real deployment
  must use TLS (port 8883) with the same identities.

## 8. Timing tables

| Value | Demo time on (default) | Demo time off (protocol default) |
|---|---|---|
| Baseline sampling | 30 s | 900 s |
| Investigation sampling | 2 s | 30 s |
| Battery-aware sampling below `battery_low_pct` (15) | baseline x 2 | baseline x 2 |
| Task duration | 180 s | 1,800 s |
| Task cooldown per zone | 30 s | 900 s |
| Verified sensor window | 120 s | 86,400 s |
| Capture interval | 10 s | 10 s |
| Offline after silence | 3 x current interval | 3 x current interval |
| Late sample | older than 2 x the interval of the sample's own mode, at receipt | same |
| Command retry | one re-send if unacknowledged after 5 s | same |
| Command expiry | `expires_at` carried in the command | same |
| MQTT keep-alive / session expiry | 30 s / 3,600 s | same |
| Scenario ramp (simulator) | 60 s default; Recovery 120 s; porewater salinity under salt intrusion 180 s | same |

The tide period is 12.42 h; fast-forward changes the simulated tide only, never message timestamps.

## 9. Edge-logic reference

This is what the reference firmware (`services/simulator/src/bcs_sim/edge.py`) does. A real node should
behave the same way.

1. **Boot.** New random 12-hex `boot_id`; telemetry `seq` and event `seq` reset to 0; a `boot` event is
   announced with `details.reason` (`power_on`, or `reboot_command`). The node publishes retained
   `status: online`, then applies the retained `config`.
2. **Sampling.** Sample when `now - last_sample >= interval`; the first sample is taken immediately.
   Baseline uses `baseline_interval_s` (doubled when battery < `battery_low_pct`); investigation uses
   `interval_s` from the command, else `investigation_interval_s`.
3. **Rolling window.** Per reading, the last `anomaly.window` (30) values. A spike check needs at least
   5 values of history.
4. **Spike.** `z = (v - mean) / max(stdev, eps)`; if `|z| > z_threshold` (3.0), flag `spike` with score
   `z` and emit an `anomaly` event (`details.z`). Per sample, no latching.
5. **Threshold.** Critical when `v < min` or `v > max` of the reading's `critical_bands`. Flag
   `threshold` (score = value) and a `threshold` event fire only on the first transition from not
   critical to critical, per parameter.
6. **Stuck.** When the last `stuck_window` (10) values span less than `stuck_epsilon[reading]` (default
   0.001), flag `stuck` (score = spread) on every sample while it holds; one `stuck` event on the
   rising edge.
7. **Battery.** Below `battery_low_pct`, flag `battery` on `battery_pct` (score = deficit) every sample
   and emit one `battery_low` event on the rising edge. Each sample drains the battery.
8. **Events.** Every event takes the next value of the per-boot event counter when it is created.
9. **Commands.**
   - Expired (`expires_at` earlier than receipt): ack `expired`.
   - `ping`: ack `accepted` (reason `pong`).
   - `reboot`: ack `accepted`, then re-boot as in step 1 with all windows cleared.
   - `set_mode` baseline: return to baseline; a running investigation command is acked `completed`
     (reason `superseded`); then `accepted`.
   - `set_mode` investigation: needs `duration_s > 0`, otherwise `rejected`; a running investigation
     command is acked `completed` (`superseded`); then `accepted`. When `duration_s` elapses the node
     returns to baseline and acks `completed`.
   - `set_config`: merge the partial config over the current one and validate; invalid is `rejected`,
     valid is applied and acked `accepted`, followed by a `config_applied` event (`config_version` and
     both intervals in `details`).
   - Unknown type: `rejected`.
10. **Config.** A retained `config` is applied on receipt, with a `config_applied` event. Changing
    `anomaly.window` resizes the rolling windows, keeping existing samples.
11. **Last will.** Registered at connect: retained `status` with `state: offline`, `reason: last_will`.
    A clean shutdown publishes the same with `reason: shutdown`.

## 10. Rejection cases

Each message type has one valid and one invalid example in section 3, checked by the contract test.
Further cases the Ground Station rejects (section 5): unknown or decommissioned node; `node_type`
different from the registry; a reading outside its physical range; `sampled_at` more than 60 s in the
future; payload site or node not matching the topic; non-JSON bytes. A duplicate (node, boot, seq) is
silently dropped.

## 11. Real hardware checklist for a future node

- [ ] Set `source: "hardware"` and `replay: false` on every message.
- [ ] Obtain a node ID and device key from the Ground Station; keep the key in non-volatile memory.
- [ ] Connect with MQTT v5, `clean_start = false`, session expiry 3,600 s, keep-alive 30 s, client ID
      = user name = node ID.
- [ ] Register the last-will status (retained, `offline`, `last_will`) before connecting; publish retained
      `online` after connecting.
- [ ] Generate a new random 12-hex `boot_id` on every boot; reset both sequence counters to 0.
- [ ] Use UTC time with milliseconds (NTP or RTC); `sampled_at` must never run ahead of real time.
- [ ] Subscribe to your own `cmd` and `config` topics only; apply the retained config before sampling.
- [ ] Report only the readings of your node type, within the ranges and resolutions of section 4.
- [ ] Implement the edge logic of section 9 (spike, threshold, stuck, battery) and the event kinds.
- [ ] Acknowledge every command (`accepted`, `rejected`, `completed`, `expired`) and drop expired ones.
- [ ] Return to baseline automatically when an investigation command ends.
- [ ] Double the baseline interval below the low-battery level and flag it.
- [ ] Keep QoS 1 in-flight messages at 20 or fewer; send late rather than drop samples.
- [ ] Use TLS on the production broker.
- [ ] Run your sample messages through `services/ground-station/tests/contract` before first connection.
