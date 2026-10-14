#pragma once
#include <Arduino.h>

// NVS namespace "sys" (L9): reboot_count, last_reset, drd_flag.
struct SysInfo {
  uint32_t reboot_count = 0;
  String reset_reason;
};

// Reads the restart record and bumps reboot_count. Returns whether drd_flag was already set.
bool sys_boot(SysInfo* info);
void sys_drd_set(bool on);
const SysInfo& sys_info();
