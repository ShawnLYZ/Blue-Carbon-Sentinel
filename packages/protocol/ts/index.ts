// Sentinel Protocol v1 TypeScript surface. Types are generated from packages/protocol/schemas.
export type { Telemetry } from "./generated/telemetry.schema";
export type { Status } from "./generated/status.schema";
export type { NodeEvent } from "./generated/event.schema";
export type { Command } from "./generated/cmd.schema";
export type { Ack } from "./generated/ack.schema";
export type { NodeConfig } from "./generated/config.schema";

/** Reading keys per node type (addendum G4); mirrors READING_KEYS in bcs_protocol.validate. */
export const READING_KEYS = {
  water_quality: ["salinity_psu", "turbidity_ntu", "do_mg_l", "temp_c", "ph"],
  soil_probe: ["porewater_salinity_psu", "soil_moisture_pct"],
  tide_gauge: ["water_level_cm"],
} as const;
