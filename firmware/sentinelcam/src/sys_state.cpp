#include "sys_state.h"
#include <Preferences.h>
#include "esp_system.h"

namespace {
SysInfo g_info;

const char* reason_name(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "external";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
  }
}
}  // namespace

bool sys_boot(SysInfo* info) {
  Preferences p;
  p.begin("sys", false);
  bool drd = p.getBool("drd_flag", false);
  g_info.reboot_count = p.getUInt("reboot_count", 0) + 1;
  g_info.reset_reason = reason_name(esp_reset_reason());
  p.putUInt("reboot_count", g_info.reboot_count);
  p.putString("last_reset", g_info.reset_reason);
  p.end();
  if (info) *info = g_info;
  return drd;
}

void sys_drd_set(bool on) {
  Preferences p;
  p.begin("sys", false);
  p.putBool("drd_flag", on);
  p.end();
}

const SysInfo& sys_info() { return g_info; }
