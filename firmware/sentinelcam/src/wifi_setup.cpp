#include "wifi_setup.h"
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <WiFiManager.h>
#include <vector>
#include "bcs_core.h"
#include "bcs_config.h"

namespace {
WiFiMulti g_multi;
size_t g_saved = 0;

// NVS namespace "wifi" (L9): count, ssid0..ssid4, pass0..pass4.
std::vector<Net> load_nets() {
  std::vector<Net> out;
  Preferences p;
  p.begin("wifi", true);
  uint32_t n = p.getUInt("count", 0);
  if (n > kMaxNets) n = kMaxNets;
  for (uint32_t i = 0; i < n; i++) {
    String s = p.getString(("ssid" + String(i)).c_str(), "");
    String w = p.getString(("pass" + String(i)).c_str(), "");
    if (s.length()) out.push_back(Net{s.c_str(), w.c_str()});
  }
  p.end();
  return out;
}

void save_nets(const std::vector<Net>& list) {
  Preferences p;
  p.begin("wifi", false);
  p.putUInt("count", list.size());
  for (size_t i = 0; i < kMaxNets; i++) {
    String is(i);
    if (i < list.size()) {
      p.putString(("ssid" + is).c_str(), list[i].ssid.c_str());
      p.putString(("pass" + is).c_str(), list[i].pass.c_str());
    } else {
      p.remove(("ssid" + is).c_str());
      p.remove(("pass" + is).c_str());
    }
  }
  p.end();
}

[[noreturn]] void run_portal() {
  Serial.println("portal: " BCS_PORTAL_SSID);
  WiFi.mode(WIFI_AP_STA);
  WiFiManager wm;
  wm.setDebugOutput(false);  // its debug log prints the entered password
  wm.setConfigPortalTimeout(BCS_PORTAL_TIMEOUT_S);
  wm.setConnectTimeout(BCS_WIFI_TIMEOUT_MS / 1000);
  wm.setConnectRetries(3);
  // Return on every save so a failed join is reported instead of silently reopening the portal.
  bool submitted = false;
  wm.setBreakAfterConfig(true);
  wm.setSaveConfigCallback([&submitted] { submitted = true; });
  if (wm.startConfigPortal(BCS_PORTAL_SSID)) {
    std::vector<Net> list = load_nets();
    list = netlist_add(list, Net{WiFi.SSID().c_str(), WiFi.psk().c_str()});
    save_nets(list);
    Serial.println("portal: network saved, restarting");
  } else if (submitted) {
    Serial.printf("portal: join failed (%s), not saved\n", wm.getWLStatusString(wm.getLastConxResult()).c_str());
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n && i < 8; i++) Serial.printf("portal: seen %s rssi %d\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i));
  } else {
    Serial.println("portal: timed out, restarting");
  }
  delay(500);
  ESP.restart();
  while (true) delay(1000);
}
}  // namespace

size_t wifi_saved_count() { return g_saved; }

void wifi_start(bool open_portal) {
  WiFi.persistent(false);  // networks live only in our NVS list
  WiFi.setHostname(BCS_HOSTNAME);
  std::vector<Net> nets = load_nets();
  g_saved = nets.size();
  if (open_portal || nets.empty()) run_portal();

  WiFi.mode(WIFI_STA);
  // L8 asked for 8.5 dBm until connected; on the real board that power never completes a join
  // (one weak neighbour seen, auth timeouts), while full power joins in ~7 s with no brownout.
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  for (const Net& n : nets) g_multi.addAP(n.ssid.c_str(), n.pass.c_str());
  // WiFiMulti::run returns at once when one scan misses every saved network, so keep trying
  // for the whole connect window before falling back to the portal.
  uint32_t start = millis();
  while (g_multi.run(10000) != WL_CONNECTED) {
    if (millis() - start >= BCS_WIFI_TIMEOUT_MS) {
      int seen = WiFi.scanNetworks();  // say what the radio can hear before giving up
      for (int i = 0; i < seen && i < 8; i++) Serial.printf("wifi: seen %s ch %d rssi %d\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));
      Serial.printf("wifi: %u saved network(s) not joined\n", (unsigned)nets.size());
      run_portal();
    }
    delay(500);
  }

  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  Serial.printf("wifi: connected to %s, ip %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
}
