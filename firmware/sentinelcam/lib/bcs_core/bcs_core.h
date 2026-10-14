// Pure C++ core of the SentinelCam firmware. No Arduino headers: unit-tested natively.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

// Double-reset detection (addendum A9, L9): flag set at boot, cleared after 5 s of uptime.
enum class DrdDecision { Normal, OpenPortal };
DrdDecision drd_on_boot(bool flag_was_set);
bool drd_should_clear(uint32_t uptime_ms);

// Saved networks (addendum L2): newest first, de-duplicated by SSID, at most 5.
struct Net { std::string ssid, pass; };
constexpr size_t kMaxNets = 5;
std::vector<Net> netlist_add(std::vector<Net> list, Net n);

// Token check (addendum L3): "Authorization: Bearer <t>" or ?token=<t>; constant-time compare.
bool auth_ok(const char* auth_header, const char* query_token, const char* expected);

// Control field validation (addendum L5): v must be an integer in [lo, hi]. The range is checked
// on the double before any int conversion, so huge or non-finite values never reach a cast.
bool int_in_range(double v, int lo, int hi);

// Gain ceiling is the I3 index 0..6 (maps to the sensor's 2x..128x gainceiling_t).
constexpr int kGainCeilingMin = 0, kGainCeilingMax = 6;
