#include "http_api.h"
#include <atomic>
#include <WiFi.h>
#include "cJSON.h"
#include "esp_http_server.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "bcs_config.h"
#include "bcs_core.h"
#include "camera.h"
#include "ota.h"
#include "sys_state.h"
#include "wifi_setup.h"

namespace {
std::atomic<bool> g_streaming{false};
std::atomic<uint32_t> g_frames_sent{0};
std::atomic<uint32_t> g_fps_x10{0};

uint32_t uptime_ms() { return (uint32_t)(esp_timer_get_time() / 1000); }

// Bearer header or ?token= (L3). Anything else is 401.
bool authorised(httpd_req_t* req) {
  char* hdr = nullptr;
  size_t hl = httpd_req_get_hdr_value_len(req, "Authorization");
  if (hl > 0 && hl < 512) {
    hdr = (char*)malloc(hl + 1);
    if (hdr && httpd_req_get_hdr_value_str(req, "Authorization", hdr, hl + 1) != ESP_OK) {
      free(hdr);
      hdr = nullptr;
    }
  }
  char qtok[160] = {0};
  const char* qp = nullptr;
  size_t ql = httpd_req_get_url_query_len(req);
  if (ql > 0 && ql < 400) {
    char* q = (char*)malloc(ql + 1);
    if (q) {
      if (httpd_req_get_url_query_str(req, q, ql + 1) == ESP_OK &&
          httpd_query_key_value(q, "token", qtok, sizeof(qtok)) == ESP_OK)
        qp = qtok;
      free(q);
    }
  }
  bool ok = auth_ok(hdr, qp, BCS_CAMERA_TOKEN);
  if (hdr) free(hdr);
  return ok;
}

esp_err_t send_401(httpd_req_t* req) {
  httpd_resp_set_status(req, "401 Unauthorized");
  httpd_resp_set_hdr(req, "WWW-Authenticate", "Bearer");
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, "{\"error\":\"unauthorized\"}");
}

esp_err_t send_error(httpd_req_t* req, const char* status, const char* msg) {
  httpd_resp_set_status(req, status);
  httpd_resp_set_type(req, "application/json");
  String body = String("{\"error\":\"") + msg + "\"}";
  return httpd_resp_sendstr(req, body.c_str());
}

esp_err_t send_json(httpd_req_t* req, cJSON* root) {
  char* s = cJSON_PrintUnformatted(root);
  cJSON_Delete(root);
  if (!s) return send_error(req, "500 Internal Server Error", "out of memory");
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t r = httpd_resp_sendstr(req, s);
  free(s);
  return r;
}

cJSON* status_json() {
  CamSettings c = camera_settings();
  cJSON* o = cJSON_CreateObject();
  cJSON_AddStringToObject(o, "fw_version", BCS_FW_VERSION);
  cJSON_AddStringToObject(o, "device_id", BCS_DEVICE_ID);
  cJSON_AddStringToObject(o, "hostname", BCS_HOSTNAME);
  cJSON_AddStringToObject(o, "ip", WiFi.localIP().toString().c_str());
  cJSON_AddStringToObject(o, "mac", WiFi.macAddress().c_str());
  cJSON_AddStringToObject(o, "ssid", WiFi.SSID().c_str());
  cJSON_AddNumberToObject(o, "rssi_dbm", WiFi.RSSI());
  cJSON_AddNumberToObject(o, "uptime_s", uptime_ms() / 1000);
  cJSON_AddNumberToObject(o, "free_heap", ESP.getFreeHeap());
  cJSON_AddNumberToObject(o, "free_psram", ESP.getFreePsram());
  cJSON_AddStringToObject(o, "frame_size", frame_size_name(c.frame_size));
  cJSON_AddNumberToObject(o, "jpeg_quality", c.jpeg_quality);
  cJSON_AddNumberToObject(o, "fps", g_fps_x10.load() / 10.0);
  cJSON_AddNumberToObject(o, "frames_sent", g_frames_sent.load());
  cJSON_AddNumberToObject(o, "stream_clients", g_streaming.load() ? 1 : 0);
  cJSON_AddBoolToObject(o, "ae_locked", c.ae_locked);
  cJSON_AddBoolToObject(o, "awb_locked", c.awb_locked);
  cJSON_AddBoolToObject(o, "vflip", c.vflip);
  cJSON_AddBoolToObject(o, "hmirror", c.hmirror);
  cJSON_AddBoolToObject(o, "flash", c.flash);
  cJSON_AddNumberToObject(o, "gain_ceiling", c.gain_ceiling);
  cJSON_AddStringToObject(o, "reset_reason", sys_info().reset_reason.c_str());
  cJSON_AddNumberToObject(o, "reboot_count", sys_info().reboot_count);
  cJSON_AddNumberToObject(o, "camera_errors", camera_error_count());
  cJSON_AddNumberToObject(o, "wifi_networks_saved", wifi_saved_count());
  return o;
}

esp_err_t status_handler(httpd_req_t* req) { return send_json(req, status_json()); }

esp_err_t capture_handler(httpd_req_t* req) {
  if (!authorised(req)) return send_401(req);
  if (ota_active()) return send_error(req, "503 Service Unavailable", "ota in progress");
  camera_fb_t* fb = camera_grab();
  if (!fb) return send_error(req, "503 Service Unavailable", "no frame");
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  char ms[16];
  snprintf(ms, sizeof(ms), "%u", (unsigned)uptime_ms());
  httpd_resp_set_hdr(req, "X-Uptime-Ms", ms);
  esp_err_t r = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  camera_release(fb);
  return r;
}

// Reads a JSON body (L5) into c. Returns an error text, or nullptr on success.
const char* parse_control(const char* body, Control* c) {
  cJSON* root = cJSON_Parse(body);
  if (!cJSON_IsObject(root)) { cJSON_Delete(root); return "body must be a JSON object"; }
  const char* err = nullptr;
  cJSON* v;
  if ((v = cJSON_GetObjectItemCaseSensitive(root, "frame_size"))) {
    framesize_t fs;
    if (!cJSON_IsString(v) || !frame_size_from_name(v->valuestring, &fs)) err = "invalid frame_size";
    else c->frame_size = fs;
  }
  if (!err && (v = cJSON_GetObjectItemCaseSensitive(root, "jpeg_quality"))) {
    if (!cJSON_IsNumber(v) || !int_in_range(v->valuedouble, 4, 63))
      err = "jpeg_quality must be an integer 4..63";
    else c->jpeg_quality = (int)v->valuedouble;
  }
  if (!err && (v = cJSON_GetObjectItemCaseSensitive(root, "gain_ceiling"))) {
    if (!cJSON_IsNumber(v) || !int_in_range(v->valuedouble, kGainCeilingMin, kGainCeilingMax))
      err = "gain_ceiling must be an integer 0..6";
    else c->gain_ceiling = (int)v->valuedouble;
  }
  struct { const char* key; int* dst; } flags[] = {
      {"vflip", &c->vflip}, {"hmirror", &c->hmirror}, {"flash", &c->flash},
      {"ae_lock", &c->ae_lock}, {"awb_lock", &c->awb_lock}};
  for (auto& f : flags) {
    if (err) break;
    if ((v = cJSON_GetObjectItemCaseSensitive(root, f.key))) {
      if (!cJSON_IsBool(v)) err = "boolean field expected";
      else *f.dst = cJSON_IsTrue(v) ? 1 : 0;
    }
  }
  cJSON_Delete(root);
  return err;
}

esp_err_t control_handler(httpd_req_t* req) {
  if (!authorised(req)) return send_401(req);
  if (ota_active()) return send_error(req, "503 Service Unavailable", "ota in progress");
  size_t n = req->content_len;
  if (n == 0 || n > 512) return send_error(req, "400 Bad Request", "body size must be 1..512 bytes");
  char buf[513];
  size_t got = 0;
  int timeouts = 0;
  while (got < n) {
    int r = httpd_req_recv(req, buf + got, n - got);
    if (r == HTTPD_SOCK_ERR_TIMEOUT && ++timeouts < 3) continue;  // a stalled client must not hold port 80
    if (r <= 0) {
      if (r == HTTPD_SOCK_ERR_TIMEOUT) httpd_resp_send_err(req, HTTPD_408_REQ_TIMEOUT, nullptr);
      return ESP_FAIL;
    }
    got += r;
  }
  buf[got] = 0;
  Control c;
  if (const char* err = parse_control(buf, &c)) return send_error(req, "400 Bad Request", err);
  camera_set(c);
  return send_json(req, status_json());
}

// ---- Port 81 stream (L3) ------------------------------------------------------------------
// ESP-IDF httpd serves every socket of an instance from one task, so a long-running stream handler
// would starve a second client instead of answering 503. Port 81 is therefore a small WiFiServer:
// the accept task is always responsive and hands an accepted client to a dedicated stream task.
WiFiServer g_stream_server(BCS_STREAM_PORT);

bool write_all(WiFiClient& c, const uint8_t* p, size_t n) {
  uint32_t last_progress = millis();
  while (n > 0) {
    if (!c.connected()) return false;
    size_t w = c.write(p, n);
    if (w > 0) { p += w; n -= w; last_progress = millis(); }
    else if (millis() - last_progress > 5000) return false;
    else vTaskDelay(pdMS_TO_TICKS(5));
  }
  return true;
}

void reply_simple(WiFiClient& c, const char* status, const char* extra_hdr) {
  String r = String("HTTP/1.1 ") + status + "\r\nContent-Type: application/json\r\n" + extra_hdr +
             "Content-Length: 0\r\nConnection: close\r\n\r\n";
  write_all(c, (const uint8_t*)r.c_str(), r.length());
}

// Reads the request head (<= 1 KiB, <= 3 s). Returns false on timeout/overflow.
bool read_head(WiFiClient& c, String* head) {
  uint32_t t0 = millis();
  while (millis() - t0 < 3000 && head->length() < 1024) {
    if (!c.connected() && !c.available()) return false;
    while (c.available() && head->length() < 1024) {
      *head += (char)c.read();
      if (head->endsWith("\r\n\r\n")) return true;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  return false;
}

// Extracts the Authorization value and ?token= from a request head. Returns the request path in *path.
void parse_head(const String& head, String* path, String* auth, String* qtoken, bool* is_get) {
  int eol = head.indexOf("\r\n");
  String line = head.substring(0, eol < 0 ? head.length() : eol);
  *is_get = line.startsWith("GET ");
  int sp1 = line.indexOf(' '), sp2 = line.indexOf(' ', sp1 + 1);
  String target = (sp1 >= 0 && sp2 > sp1) ? line.substring(sp1 + 1, sp2) : String("");
  int q = target.indexOf('?');
  *path = q < 0 ? target : target.substring(0, q);
  if (q >= 0) {
    String qs = "&" + target.substring(q + 1);
    int k = qs.indexOf("&token=");
    if (k >= 0) {
      int s = k + 7, e = qs.indexOf('&', s);
      *qtoken = qs.substring(s, e < 0 ? qs.length() : e);
    }
  }
  int pos = eol;
  while (pos >= 0 && pos < (int)head.length()) {
    int next = head.indexOf("\r\n", pos + 2);
    if (next < 0) break;
    String h = head.substring(pos + 2, next);
    if (h.length() > 14 && h.substring(0, 14).equalsIgnoreCase("authorization:")) {
      *auth = h.substring(14);
      auth->trim();
    }
    pos = next;
  }
}

void stream_task(void* arg) {
  WiFiClient* cp = (WiFiClient*)arg;
  WiFiClient& client = *cp;
  client.setNoDelay(true);
  esp_task_wdt_add(NULL);  // L8: a stuck send or capture resets the board
  static const char kHead[] =
      "HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=bcsframe\r\n"
      "Cache-Control: no-store\r\nConnection: close\r\n\r\n";
  bool ok = write_all(client, (const uint8_t*)kHead, sizeof(kHead) - 1);
  uint32_t seq = 0, window_start = uptime_ms(), window_frames = 0;
  while (ok && !ota_active()) {
    esp_task_wdt_reset();
    camera_fb_t* fb = camera_grab();
    if (!fb) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
    char part[200];
    int hl = snprintf(part, sizeof(part),
                      "--bcsframe\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n"
                      "X-Frame-Seq: %u\r\nX-Uptime-Ms: %u\r\n\r\n",
                      (unsigned)fb->len, (unsigned)seq, (unsigned)uptime_ms());
    ok = write_all(client, (const uint8_t*)part, hl) && write_all(client, fb->buf, fb->len) &&
         write_all(client, (const uint8_t*)"\r\n", 2);
    camera_release(fb);
    if (!ok) break;
    seq++;
    g_frames_sent++;
    window_frames++;
    uint32_t now = uptime_ms();
    if (now - window_start >= 1000) {
      g_fps_x10 = window_frames * 10000 / (now - window_start);
      window_start = now;
      window_frames = 0;
    }
  }
  g_fps_x10 = 0;
  esp_task_wdt_delete(NULL);
  client.stop();
  delete cp;
  g_streaming = false;
  vTaskDelete(nullptr);
}

void accept_task(void*) {
  g_stream_server.begin();
  for (;;) {
    WiFiClient c = g_stream_server.available();
    if (!c) { vTaskDelay(pdMS_TO_TICKS(10)); continue; }
    String head, path, auth, qtoken;
    bool is_get = false;
    if (!read_head(c, &head)) { c.stop(); continue; }
    parse_head(head, &path, &auth, &qtoken, &is_get);
    if (!is_get) { reply_simple(c, "405 Method Not Allowed", ""); c.stop(); continue; }
    if (path != "/stream") { reply_simple(c, "404 Not Found", ""); c.stop(); continue; }
    if (!auth_ok(auth.length() ? auth.c_str() : nullptr, qtoken.length() ? qtoken.c_str() : nullptr,
                 BCS_CAMERA_TOKEN)) {
      reply_simple(c, "401 Unauthorized", "WWW-Authenticate: Bearer\r\n");
      c.stop();
      continue;
    }
    if (ota_active()) { reply_simple(c, "503 Service Unavailable", ""); c.stop(); continue; }
    bool expected = false;
    if (!g_streaming.compare_exchange_strong(expected, true)) {  // one client at a time (L3)
      reply_simple(c, "503 Service Unavailable", "");
      c.stop();
      continue;
    }
    WiFiClient* heap_client = new WiFiClient(c);
    if (xTaskCreate(stream_task, "stream", 6144, heap_client, 2, nullptr) != pdPASS) {
      delete heap_client;
      g_streaming = false;
      reply_simple(c, "503 Service Unavailable", "");
      c.stop();
    }
  }
}

httpd_handle_t start_server(uint16_t port, uint16_t ctrl_port, const httpd_uri_t* uris, size_t n) {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = port;
  cfg.ctrl_port = ctrl_port;
  cfg.max_uri_handlers = 8;
  cfg.stack_size = 8192;
  cfg.lru_purge_enable = true;
  httpd_handle_t h = nullptr;
  if (httpd_start(&h, &cfg) != ESP_OK) return nullptr;
  for (size_t i = 0; i < n; i++) httpd_register_uri_handler(h, &uris[i]);
  return h;
}
}  // namespace

bool http_begin() {
  esp_task_wdt_init(BCS_STREAM_WDT_S, true);
  const httpd_uri_t api[] = {
      {"/status", HTTP_GET, status_handler, nullptr},
      {"/capture", HTTP_GET, capture_handler, nullptr},
      {"/control", HTTP_POST, control_handler, nullptr},
  };
  bool a = start_server(BCS_HTTP_PORT, 32768, api, 3) != nullptr;
  bool s = xTaskCreate(accept_task, "stream_accept", 4096, nullptr, 2, nullptr) == pdPASS;
  return a && s;
}
