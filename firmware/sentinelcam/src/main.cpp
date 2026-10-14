// SentinelCam (addendum L). Start-up order: 500 ms settle -> camera -> Wi-Fi -> mDNS -> HTTP -> OTA.
#include <Arduino.h>
#include <ESPmDNS.h>
#include <WiFi.h>
#include "bcs_config.h"
#include "bcs_core.h"
#include "camera.h"
#include "http_api.h"
#include "ota.h"
#include "sys_state.h"
#include "wifi_setup.h"

// Clears drd_flag at 5 s of uptime regardless of how long setup() blocks in Wi-Fi (L9).
static void drd_clear_task(void*) {
  while (!drd_should_clear(millis())) vTaskDelay(pdMS_TO_TICKS(100));
  sys_drd_set(false);
  vTaskDelete(nullptr);
}

void setup() {
  pinMode(BCS_FLASH_GPIO, OUTPUT);
  digitalWrite(BCS_FLASH_GPIO, LOW);
  Serial.begin(115200);
  Serial.println("SentinelCam " BCS_FW_VERSION " booting");

  bool flag_was_set = sys_boot(nullptr);
  bool portal = drd_on_boot(flag_was_set) == DrdDecision::OpenPortal;
  // Flag goes up before the settle so a reset inside it counts. A portal boot clears it at once
  // so the post-save reboot is a normal boot.
  sys_drd_set(!portal);
  if (!portal) xTaskCreate(drd_clear_task, "drd_clear", 4096, nullptr, 1, nullptr);
  delay(BCS_SETTLE_MS);

  if (!camera_begin()) Serial.println("camera: not available, retrying on demand");
  wifi_start(portal);  // portal path reboots and never returns

  if (MDNS.begin(BCS_HOSTNAME)) {
    MDNS.addService("http", "tcp", BCS_HTTP_PORT);
    MDNS.addServiceTxt("http", "tcp", "device", BCS_DEVICE_ID);
    MDNS.addServiceTxt("http", "tcp", "fw", BCS_FW_VERSION);
    MDNS.addServiceTxt("http", "tcp", "stream_port", String(BCS_STREAM_PORT));
  } else {
    Serial.println("mdns: failed");
  }
  if (!http_begin()) Serial.println("http: failed to start");
  ota_begin();
  Serial.println("ready");
}

void loop() {
  ota_handle();
  delay(5);
}
