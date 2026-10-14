#pragma once
#include <Arduino.h>

// Connects to the strongest saved network, or opens the "SentinelCam-Setup" portal
// (double reset, or no known network within ~20 s). A saved portal result reboots the board.
void wifi_start(bool open_portal);
size_t wifi_saved_count();
