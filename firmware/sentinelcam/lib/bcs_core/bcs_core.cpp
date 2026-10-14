#include "bcs_core.h"
#include <cstring>

DrdDecision drd_on_boot(bool flag_was_set) {
  return flag_was_set ? DrdDecision::OpenPortal : DrdDecision::Normal;
}

bool drd_should_clear(uint32_t uptime_ms) { return uptime_ms >= 5000; }

std::vector<Net> netlist_add(std::vector<Net> list, Net n) {
  std::vector<Net> out;
  out.reserve(kMaxNets);
  out.push_back(std::move(n));
  for (auto& e : list) {
    if (out.size() >= kMaxNets) break;
    if (e.ssid == out[0].ssid) continue;
    out.push_back(std::move(e));
  }
  return out;
}

// Compares every byte of the expected length; no early exit on a mismatching byte.
static bool ct_equal(const char* a, size_t alen, const char* b, size_t blen) {
  if (alen != blen) return false;  // length is not secret enough to matter; mismatch is false
  unsigned char diff = 0;
  for (size_t i = 0; i < alen; i++) diff |= static_cast<unsigned char>(a[i] ^ b[i]);
  return diff == 0;
}

bool auth_ok(const char* auth_header, const char* query_token, const char* expected) {
  if (!expected || !*expected) return false;
  const size_t elen = std::strlen(expected);
  static const char kBearer[] = "Bearer ";
  const size_t plen = sizeof(kBearer) - 1;
  bool ok = false;
  if (auth_header && std::strncmp(auth_header, kBearer, plen) == 0) {
    const char* t = auth_header + plen;
    ok = ct_equal(t, std::strlen(t), expected, elen);
  }
  if (query_token) {
    ok = ct_equal(query_token, std::strlen(query_token), expected, elen) || ok;
  }
  return ok;
}

bool int_in_range(double v, int lo, int hi) {
  if (!(v >= lo && v <= hi)) return false;  // also rejects NaN
  return v == static_cast<double>(static_cast<int>(v));
}
