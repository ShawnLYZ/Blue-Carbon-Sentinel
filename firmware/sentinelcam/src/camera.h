#pragma once
#include <Arduino.h>
#include "esp_camera.h"

// Partial settings update (L5). -1 means "leave unchanged".
struct Control {
  int frame_size = -1;    // framesize_t
  int jpeg_quality = -1;  // 4..63
  int vflip = -1, hmirror = -1, flash = -1, ae_lock = -1, awb_lock = -1;  // 0/1
  int gain_ceiling = -1;  // I3 index 0..6 (gainceiling_t: 0 = 2x .. 6 = 128x)
};

struct CamSettings {
  framesize_t frame_size = FRAMESIZE_SVGA;
  int jpeg_quality = 12;
  bool vflip = false, hmirror = false, flash = false, ae_locked = false, awb_locked = false;
  int gain_ceiling = 2;  // I3 index (2 = GAINCEILING_8X)
};

bool camera_begin();  // flash LED low, init with the L1 defaults
void camera_set(const Control& c);
CamSettings camera_settings();
uint32_t camera_error_count();
bool camera_ready();

// Frame access with the L8 recovery policy. Release every frame with camera_release.
camera_fb_t* camera_grab();
void camera_release(camera_fb_t* fb);

bool frame_size_from_name(const char* name, framesize_t* out);
const char* frame_size_name(framesize_t fs);
