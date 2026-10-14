#include "ota.h"
#include <ArduinoOTA.h>
#include <atomic>
#include "bcs_config.h"

namespace {
std::atomic<bool> g_active{false};
}

bool ota_active() { return g_active.load(); }

void ota_begin() {
  ArduinoOTA.setHostname(BCS_HOSTNAME);
  ArduinoOTA.setPort(BCS_OTA_PORT);
  ArduinoOTA.setPassword(BCS_CAMERA_OTA_PASSWORD);
  ArduinoOTA.setMdnsEnabled(false);  // main.cpp owns mDNS
  ArduinoOTA.onStart([]() {
    g_active = true;
    Serial.println("ota: start");
  });
  ArduinoOTA.onEnd([]() { Serial.println("ota: done"); });
  ArduinoOTA.onError([](ota_error_t e) {
    g_active = false;  // failed update: resume streaming
    Serial.printf("ota: error %u\n", (unsigned)e);
  });
  ArduinoOTA.begin();
}

void ota_handle() { ArduinoOTA.handle(); }
