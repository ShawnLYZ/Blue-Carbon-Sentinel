// SentinelCam build configuration (addendum L). No credentials live here: the camera token and
// OTA password arrive as string macros from scripts/inject_secrets.py; Wi-Fi networks live in NVS.
#pragma once

#ifndef BCS_CAMERA_TOKEN
#error "BCS_CAMERA_TOKEN missing: build through scripts/fw.ps1 or set it in the environment/.env"
#endif
#ifndef BCS_CAMERA_OTA_PASSWORD
#error "BCS_CAMERA_OTA_PASSWORD missing: build through scripts/fw.ps1 or set it in the environment/.env"
#endif
#ifndef BCS_FW_VERSION
#define BCS_FW_VERSION "dev"
#endif

#define BCS_DEVICE_ID "CAM-01"
#define BCS_HOSTNAME "sentinel-cam"
#define BCS_PORTAL_SSID "SentinelCam-Setup"
#define BCS_HTTP_PORT 80
#define BCS_STREAM_PORT 81
#define BCS_OTA_PORT 3232

#define BCS_SETTLE_MS 500                // brownout-safe settle before camera init (L8)
#define BCS_WIFI_TIMEOUT_MS 20000        // known-network connect window (L2)
#define BCS_PORTAL_TIMEOUT_S 180         // portal gives up and reboots to retry known networks
#define BCS_STREAM_WDT_S 15              // task watchdog on the stream handler (L8)

#define BCS_CAM_FAILS_BEFORE_REINIT 5    // consecutive fb_get failures (L8)
#define BCS_CAM_REINITS_BEFORE_REBOOT 3  // within the window below (L8)
#define BCS_CAM_REINIT_WINDOW_MS 60000

#define BCS_FLASH_GPIO 4

// AI-Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22
