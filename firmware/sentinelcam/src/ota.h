#pragma once

void ota_begin();
void ota_handle();   // call from loop()
bool ota_active();   // true while an update runs: the stream stops, routes answer 503
