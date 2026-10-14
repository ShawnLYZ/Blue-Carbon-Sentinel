#include "camera.h"
#include <atomic>
#include <strings.h>
#include "freertos/semphr.h"
#include "bcs_config.h"

namespace {
SemaphoreHandle_t g_mu = nullptr;
CamSettings g_cur;
bool g_ready = false;
std::atomic<int> g_outstanding{0};
std::atomic<uint32_t> g_errors{0};
int g_consecutive_fails = 0;
uint32_t g_reinit_at[BCS_CAM_REINITS_BEFORE_REBOOT] = {0};
int g_reinit_n = 0;

struct FsName { const char* name; framesize_t fs; };
const FsName kSizes[] = {
    {"QQVGA", FRAMESIZE_QQVGA}, {"QVGA", FRAMESIZE_QVGA}, {"CIF", FRAMESIZE_CIF},
    {"VGA", FRAMESIZE_VGA},     {"SVGA", FRAMESIZE_SVGA}, {"XGA", FRAMESIZE_XGA},
    {"HD", FRAMESIZE_HD},       {"SXGA", FRAMESIZE_SXGA},   {"UXGA", FRAMESIZE_UXGA},
};

void lock() { xSemaphoreTake(g_mu, portMAX_DELAY); }
void unlock() { xSemaphoreGive(g_mu); }

bool init_driver() {
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM; cfg.pin_d1 = Y3_GPIO_NUM; cfg.pin_d2 = Y4_GPIO_NUM; cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM; cfg.pin_d5 = Y7_GPIO_NUM; cfg.pin_d6 = Y8_GPIO_NUM; cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk = XCLK_GPIO_NUM; cfg.pin_pclk = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM; cfg.pin_href = HREF_GPIO_NUM;
  cfg.pin_sccb_sda = SIOD_GPIO_NUM; cfg.pin_sccb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn = PWDN_GPIO_NUM; cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size = FRAMESIZE_SVGA;
  cfg.jpeg_quality = 12;
  cfg.fb_count = 2;
  cfg.fb_location = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    Serial.printf("camera: init failed 0x%x\n", (unsigned)err);
    return false;
  }
  return true;
}

// OV2640 live exposure/gain. sn->status.aec_value/agc_gain are init-time caches, so freezing
// reads the sensor-bank registers: AEC[9:2]=0x10, AEC[1:0]=REG04[1:0], AEC[15:10]=REG45[5:0], GAIN=0x00.
struct LiveAe { int aec = 0, r04 = 0, r45 = 0, gain = 0; };
LiveAe g_live;
// The driver encodes the bank in bit 8 of the register argument (0x1xx = sensor bank) and tracks it itself.

void restore_live(sensor_t* sn) {
  sn->set_reg(sn, 0x110, 0xFF, g_live.aec);
  sn->set_reg(sn, 0x104, 0x03, g_live.r04);
  sn->set_reg(sn, 0x145, 0x3F, g_live.r45);
  sn->set_reg(sn, 0x100, 0xFF, g_live.gain);
}

void freeze_ae(sensor_t* sn) {
  g_live.aec = sn->get_reg(sn, 0x110, 0xFF);
  g_live.r04 = sn->get_reg(sn, 0x104, 0x03);
  g_live.r45 = sn->get_reg(sn, 0x145, 0x3F);
  g_live.gain = sn->get_reg(sn, 0x100, 0xFF);
  sn->set_exposure_ctrl(sn, 0);
  sn->set_gain_ctrl(sn, 0);
  restore_live(sn);  // the registers now hold the values that were live at the moment of locking
}

void set_awb(sensor_t* sn, bool locked) {
  sn->set_whitebal(sn, locked ? 0 : 1);
  sn->set_awb_gain(sn, locked ? 0 : 1);
}

// Caller holds the mutex. Applies only the fields present in c.
void apply_change_locked(const Control& c, const CamSettings& s) {
  sensor_t* sn = esp_camera_sensor_get();
  if (!sn) return;
  if (c.frame_size >= 0) sn->set_framesize(sn, s.frame_size);
  if (c.jpeg_quality >= 0) sn->set_quality(sn, s.jpeg_quality);
  if (c.vflip >= 0) sn->set_vflip(sn, s.vflip);
  if (c.hmirror >= 0) sn->set_hmirror(sn, s.hmirror);
  if (c.gain_ceiling >= 0) sn->set_gainceiling(sn, (gainceiling_t)s.gain_ceiling);
  if (c.ae_lock >= 0) {
    if (s.ae_locked) freeze_ae(sn);
    else { sn->set_exposure_ctrl(sn, 1); sn->set_gain_ctrl(sn, 1); }
  }
  if (c.awb_lock >= 0) set_awb(sn, s.awb_locked);
  if (c.flash >= 0) digitalWrite(BCS_FLASH_GPIO, s.flash ? HIGH : LOW);
}

// Caller holds the mutex. Full re-apply after a (re-)initialisation.
void apply_all_locked(const CamSettings& s) {
  sensor_t* sn = esp_camera_sensor_get();
  if (!sn) return;
  sn->set_framesize(sn, s.frame_size);
  sn->set_quality(sn, s.jpeg_quality);
  sn->set_vflip(sn, s.vflip);
  sn->set_hmirror(sn, s.hmirror);
  sn->set_gainceiling(sn, (gainceiling_t)s.gain_ceiling);
  if (s.ae_locked) {  // frozen values captured when the lock was taken
    sn->set_exposure_ctrl(sn, 0);
    sn->set_gain_ctrl(sn, 0);
    restore_live(sn);
  }
  set_awb(sn, s.awb_locked);
  digitalWrite(BCS_FLASH_GPIO, s.flash ? HIGH : LOW);
}

// Caller holds the mutex. Skipped while a frame is outstanding; the next failure retries.
void recover_locked() {
  if (g_outstanding.load() != 0) return;
  uint32_t now = millis();
  // Three re-initialisations inside the window mean the sensor is not coming back: reboot.
  g_reinit_at[g_reinit_n % BCS_CAM_REINITS_BEFORE_REBOOT] = now;
  g_reinit_n++;
  if (g_reinit_n >= BCS_CAM_REINITS_BEFORE_REBOOT) {
    uint32_t oldest = g_reinit_at[g_reinit_n % BCS_CAM_REINITS_BEFORE_REBOOT];
    if (now - oldest <= BCS_CAM_REINIT_WINDOW_MS) {
      Serial.println("camera: 3 re-inits within 60 s, rebooting");
      delay(100);
      ESP.restart();
    }
  }
  Serial.println("camera: re-initialising");
  if (g_ready) esp_camera_deinit();
  g_ready = init_driver();
  if (g_ready) apply_all_locked(g_cur);
  g_consecutive_fails = 0;
}
}  // namespace

bool camera_begin() {
  pinMode(BCS_FLASH_GPIO, OUTPUT);
  digitalWrite(BCS_FLASH_GPIO, LOW);
  g_mu = xSemaphoreCreateMutex();
  lock();
  g_ready = init_driver();
  if (g_ready) apply_all_locked(g_cur);
  unlock();
  if (!g_ready) g_errors++;
  return g_ready;
}

bool camera_ready() { return g_ready; }
uint32_t camera_error_count() { return g_errors.load(); }

CamSettings camera_settings() {
  lock();
  CamSettings s = g_cur;
  unlock();
  return s;
}

void camera_set(const Control& c) {
  lock();
  if (c.frame_size >= 0) g_cur.frame_size = (framesize_t)c.frame_size;
  if (c.jpeg_quality >= 0) g_cur.jpeg_quality = c.jpeg_quality;
  if (c.vflip >= 0) g_cur.vflip = c.vflip;
  if (c.hmirror >= 0) g_cur.hmirror = c.hmirror;
  if (c.flash >= 0) g_cur.flash = c.flash;
  if (c.ae_lock >= 0) g_cur.ae_locked = c.ae_lock;
  if (c.awb_lock >= 0) g_cur.awb_locked = c.awb_lock;
  if (c.gain_ceiling >= 0) g_cur.gain_ceiling = c.gain_ceiling;
  if (g_ready) apply_change_locked(c, g_cur);
  unlock();
}

camera_fb_t* camera_grab() {
  lock();
  camera_fb_t* fb = g_ready ? esp_camera_fb_get() : nullptr;
  if (fb) {
    g_consecutive_fails = 0;
    g_outstanding++;
  } else {
    g_errors++;
    if (++g_consecutive_fails >= BCS_CAM_FAILS_BEFORE_REINIT) recover_locked();
  }
  unlock();
  return fb;
}

void camera_release(camera_fb_t* fb) {
  if (!fb) return;
  lock();
  esp_camera_fb_return(fb);
  g_outstanding--;
  unlock();
}

bool frame_size_from_name(const char* name, framesize_t* out) {
  for (const auto& e : kSizes)
    if (strcasecmp(e.name, name) == 0) { *out = e.fs; return true; }
  return false;
}

const char* frame_size_name(framesize_t fs) {
  for (const auto& e : kSizes) if (e.fs == fs) return e.name;
  return "UNKNOWN";
}
