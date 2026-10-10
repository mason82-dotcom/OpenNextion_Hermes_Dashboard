/* Hermes Touch v0.6 - LVGL multi-page dashboard with optional TLS read-only status.
 * Hardware: OpenNextion ONX3248G035 / ESP32-S3.
 * Default build has no Config.h -> NO WIFI, NO DEVICE TOKEN, NO API ACCESS.
 * Status and history explicitly distinguish local ESP32 demo values from Pi data.
 * No chat actions, no OTA, no Hermes agent configuration writes.
 */
#include <Arduino.h>
#include <cmath>
#include <stdio.h>
#include <Wire.h>
#include <SPI.h>
#include <Arduino_GFX_Library.h>
#include <Adafruit_CST8XX.h>
#include <Adafruit_PCF8574.h>
#define LV_CONF_SKIP
#include <lvgl.h>
#include "BoardConfig.h"

#if __has_include("Config.h")
#include "Config.h"
#else
#define HT_DEMO_MODE 1
#endif
#ifndef HT_DEMO_MODE
#define HT_DEMO_MODE 0
#endif

#if !HT_DEMO_MODE
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "LocalCa.h"
#ifndef HT_WIFI_SSID
#error "Config.h must define HT_WIFI_SSID"
#endif
#ifndef HT_WIFI_PASSWORD
#error "Config.h must define HT_WIFI_PASSWORD"
#endif
#ifndef HT_BRIDGE_URL
#error "Config.h must define HT_BRIDGE_URL"
#endif
#ifndef HT_DEVICE_TOKEN
#error "Config.h must define HT_DEVICE_TOKEN"
#endif
#endif

static constexpr uint32_t SAMPLE_MS = 5000;
static constexpr uint32_t WIFI_RETRY_MS = 15000;
static constexpr uint32_t LCD_SPI_FREQ = 80000000;
static constexpr uint16_t BUF_LINES = 40;
static constexpr uint8_t GRAPH_SAMPLES = 24;
static constexpr int PAGE_COUNT = 4;
static constexpr uint32_t BG = 0x101827;
static constexpr uint32_t CARD = 0x1D2C41;
static constexpr uint32_t FG = 0xE9F5FF;
static constexpr uint32_t MUTED = 0xAFC1D1;
static constexpr uint32_t CYAN = 0x50CDF4;
static constexpr uint32_t GREEN = 0x6AE3B1;

Arduino_DataBus *bus = new Arduino_HWSPI(
    LCD_DC_PIN, LCD_CS_PIN, LCD_SCLK_PIN, LCD_MOSI_PIN, LCD_MISO_PIN, &SPI, true);
Arduino_GFX *gfx = new Arduino_ST7796(
    bus, GFX_NOT_DEFINED, 0, false, LCD_H_RES, LCD_V_RES);
Adafruit_CST8XX touch;
Adafruit_PCF8574 expander;
static lv_disp_draw_buf_t drawBuf;
static lv_disp_drv_t dispDrv;
static lv_color_t dispBuf[LCD_H_RES * BUF_LINES];

static lv_obj_t *pages[PAGE_COUNT] = {nullptr};
static lv_obj_t *navBtns[PAGE_COUNT] = {nullptr};
static lv_obj_t *statusHeadline = nullptr;
static lv_obj_t *statusDetail = nullptr;
static lv_obj_t *valueA = nullptr;
static lv_obj_t *valueB = nullptr;
static lv_obj_t *valueC = nullptr;
static lv_obj_t *valueD = nullptr;
static lv_obj_t *statusFoot = nullptr;
static lv_obj_t *historyChart = nullptr;
static lv_chart_series_t *historySeries = nullptr;
static lv_obj_t *historyValue = nullptr;
static lv_obj_t *systemHeap = nullptr;
static lv_obj_t *systemPsram = nullptr;
static lv_obj_t *systemUptime = nullptr;
static lv_obj_t *systemTouches = nullptr;
static uint32_t touchActions = 0;
static uint8_t historySampleCount = 0;
static uint32_t lastSampleMs = 0;
static uint32_t lastWifiAttempt = 0;
static bool requestSample = false;
static int activePage = 0;

#if !HT_DEMO_MODE
static bool remoteValid = false;
static bool apiHealthy = false;
static bool dashboardAvailable = false;
static bool gatewayKnown = false;
static bool gatewayRunning = false;
static float piTemp = 0;
static float piRam = 0;
static float piLoad = 0;
static bool piTempKnown = false;
static bool piRamKnown = false;
static bool piLoadKnown = false;
#endif

static void panelReset() {
  if (!expander.begin(PCF8574_ADDR, &Wire)) {
    Serial.println("WARN: PCF8574 not found");
    return;
  }
  expander.digitalWriteByte(0xFF);
  delay(20);
  expander.digitalWriteByte((uint8_t)(0xFF & ~(1 << PCF8574_PIN_LCD_RST)));
  delay(120);
  expander.digitalWriteByte(0xFF);
  delay(120);
}

static void flush(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *p) {
  uint32_t w = area->x2 - area->x1 + 1;
  uint32_t h = area->y2 - area->y1 + 1;
#if LV_COLOR_16_SWAP != 0
  gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t *)&p->full, w, h);
#else
  gfx->draw16bitRGBBitmap(area->x1, area->y1, (uint16_t *)&p->full, w, h);
#endif
  lv_disp_flush_ready(drv);
}

static void touchRead(lv_indev_drv_t *, lv_indev_data_t *data) {
  static int16_t x = 0;
  static int16_t y = 0;
  if (touch.touched()) {
    CST_TS_Point point = touch.getPoint();
    x = constrain(point.x, 0, (int16_t)gfx->width() - 1);
    y = constrain(point.y, 0, (int16_t)gfx->height() - 1);
    data->state = LV_INDEV_STATE_PR;
  } else {
    data->state = LV_INDEV_STATE_REL;
  }
  data->point.x = x;
  data->point.y = y;
}

static lv_obj_t *label(lv_obj_t *parent, const char *text,
                       int x, int y, int w, uint32_t color) {
  lv_obj_t *obj = lv_label_create(parent);
  lv_obj_set_pos(obj, x, y);
  lv_obj_set_width(obj, w);
  lv_label_set_long_mode(obj, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
  lv_label_set_text(obj, text);
  return obj;
}

static lv_obj_t *card(lv_obj_t *parent, int x, int y, int w, int h) {
  lv_obj_t *obj = lv_obj_create(parent);
  lv_obj_set_pos(obj, x, y);
  lv_obj_set_size(obj, w, h);
  lv_obj_set_style_radius(obj, 12, 0);
  lv_obj_set_style_bg_color(obj, lv_color_hex(CARD), 0);
  lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(obj, 0, 0);
  lv_obj_set_style_pad_all(obj, 0, 0);
  lv_obj_clear_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
  return obj;
}

static void styleButton(lv_obj_t *btn, uint32_t bg) {
  lv_obj_set_style_bg_color(btn, lv_color_hex(bg), 0);
  lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(btn, 10, 0);
  lv_obj_set_style_border_width(btn, 0, 0);
  lv_obj_set_style_shadow_width(btn, 0, 0);
}

static void showPage(int page) {
  if (page < 0 || page >= PAGE_COUNT) return;
  activePage = page;
  for (int i = 0; i < PAGE_COUNT; ++i) {
    if (i == page) lv_obj_clear_flag(pages[i], LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(pages[i], LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(navBtns[i],
                              lv_color_hex(i == page ? 0x176A98 : 0x20334C), 0);
  }
}

static void onNav(lv_event_t *event) {
  if (lv_event_get_code(event) != LV_EVENT_CLICKED) return;
  lv_obj_t *clicked = lv_event_get_target(event);
  for (int i = 0; i < PAGE_COUNT; ++i) {
    if (clicked == navBtns[i]) {
      ++touchActions;
      showPage(i);
      return;
    }
  }
}

static void onRefresh(lv_event_t *event) {
  if (lv_event_get_code(event) == LV_EVENT_CLICKED) {
    ++touchActions;
    requestSample = true;
  }
}

static void resetHistory(lv_event_t *event) {
  if (lv_event_get_code(event) != LV_EVENT_CLICKED) return;
  ++touchActions;
  lv_chart_set_all_value(historyChart, historySeries, LV_CHART_POINT_NONE);
  historySampleCount = 0;
  requestSample = true;
}

static lv_obj_t *makePage(lv_obj_t *screen) {
  lv_obj_t *p = lv_obj_create(screen);
  lv_obj_set_pos(p, 0, 62);
  lv_obj_set_size(p, 320, 352);
  lv_obj_set_style_pad_all(p, 0, 0);
  lv_obj_set_style_border_width(p, 0, 0);
  lv_obj_set_style_bg_opa(p, LV_OPA_TRANSP, 0);
  lv_obj_clear_flag(p, LV_OBJ_FLAG_SCROLLABLE);
  return p;
}

static void buildStatusPage(lv_obj_t *p) {
  lv_obj_t *agent = card(p, 10, 8, 300, 79);
  label(agent, "HERMES-AGENT", 12, 9, 276, CYAN);
  statusHeadline = label(agent, "Offline-Test / kein Pi", 12, 31, 276, FG);
  statusDetail = label(agent, "Keine Hermes-Abfrage aktiv", 12, 55, 276, MUTED);

  lv_obj_t *a = card(p, 10, 97, 145, 86);
#if HT_DEMO_MODE
  label(a, "ESP32 HEAP", 10, 10, 125, MUTED);
#else
  label(a, "PI CPU-TEMP", 10, 10, 125, MUTED);
#endif
  valueA = label(a, "--", 10, 41, 125, FG);

  lv_obj_t *b = card(p, 165, 97, 145, 86);
#if HT_DEMO_MODE
  label(b, "ESP32 PSRAM", 10, 10, 125, MUTED);
#else
  label(b, "PI RAM", 10, 10, 125, MUTED);
#endif
  valueB = label(b, "--", 10, 41, 125, FG);

  lv_obj_t *c = card(p, 10, 193, 145, 83);
#if HT_DEMO_MODE
  label(c, "UPTIME", 10, 9, 125, MUTED);
#else
  label(c, "PI LOAD", 10, 9, 125, MUTED);
#endif
  valueC = label(c, "--", 10, 39, 125, FG);

  lv_obj_t *d = card(p, 165, 193, 145, 83);
  label(d, "TOUCH-AKTIONEN", 10, 9, 125, MUTED);
  valueD = label(d, "0", 10, 39, 125, FG);

  lv_obj_t *btn = lv_btn_create(p);
  lv_obj_set_pos(btn, 10, 284);
  lv_obj_set_size(btn, 300, 44);
  styleButton(btn, 0x157EAD);
  lv_obj_add_event_cb(btn, onRefresh, LV_EVENT_CLICKED, nullptr);
  lv_obj_t *txt = label(btn, "JETZT AKTUALISIEREN", 0, 0, 260, FG);
  lv_obj_center(txt);
  statusFoot = label(p, "Offline: nur lokale ESP32-Messwerte",
                     14, 333, 298, MUTED);
}

static void buildHistoryPage(lv_obj_t *p) {
#if HT_DEMO_MODE
  label(p, "ESP32 HEAP - VERLAUF", 13, 12, 290, CYAN);
  label(p, "Echte Messwerte vom ESP32, alle 5 s", 13, 37, 290, MUTED);
#else
  label(p, "PI CPU-TEMP - VERLAUF", 13, 12, 290, CYAN);
  label(p, "Echte Werte von der Bridge, alle 5 s", 13, 37, 290, MUTED);
#endif
  lv_obj_t *graphCard = card(p, 10, 65, 300, 194);
  historyChart = lv_chart_create(graphCard);
  lv_obj_set_pos(historyChart, 9, 11);
  lv_obj_set_size(historyChart, 282, 173);
  lv_obj_set_style_bg_color(historyChart, lv_color_hex(CARD), 0);
  lv_obj_set_style_border_width(historyChart, 0, 0);
  lv_obj_set_style_line_color(historyChart, lv_color_hex(0x36465D),
                              LV_PART_MAIN);
  lv_obj_set_style_size(historyChart, 0, LV_PART_INDICATOR);
  lv_chart_set_type(historyChart, LV_CHART_TYPE_LINE);
  lv_chart_set_div_line_count(historyChart, 4, 5);
  lv_chart_set_point_count(historyChart, GRAPH_SAMPLES);
  lv_chart_set_update_mode(historyChart, LV_CHART_UPDATE_MODE_SHIFT);
#if HT_DEMO_MODE
  lv_chart_set_range(historyChart, LV_CHART_AXIS_PRIMARY_Y, 0, 320);
#else
  lv_chart_set_range(historyChart, LV_CHART_AXIS_PRIMARY_Y, 0, 100);
#endif
  historySeries = lv_chart_add_series(
      historyChart, lv_color_hex(CYAN), LV_CHART_AXIS_PRIMARY_Y);
  lv_chart_set_all_value(historyChart, historySeries, LV_CHART_POINT_NONE);

  historyValue = label(p, "Warte auf erste Messung ...",
                       13, 266, 292, FG);
  lv_obj_t *reset = lv_btn_create(p);
  lv_obj_set_pos(reset, 10, 293);
  lv_obj_set_size(reset, 300, 45);
  styleButton(reset, 0x254A6D);
  lv_obj_add_event_cb(reset, resetHistory, LV_EVENT_CLICKED, nullptr);
  lv_obj_t *txt = label(reset, "VERLAUF ZURUECKSETZEN", 0, 0, 270, FG);
  lv_obj_center(txt);
}

static void buildSystemPage(lv_obj_t *p) {
  label(p, "GERAET / HARDWARE", 13, 13, 290, CYAN);
  lv_obj_t *hw = card(p, 10, 49, 300, 157);
  label(hw, "OpenNextion ONX3248G035", 11, 12, 278, FG);
  label(hw, "ESP32-S3  |  ST7796U  |  CST826", 11, 43, 278, MUTED);
  label(hw, "320 x 480  |  LVGL 8.3", 11, 75, 278, MUTED);
#if HT_DEMO_MODE
  label(hw, "Modus: OFFLINE (kein WLAN)", 11, 109, 278, GREEN);
#else
  label(hw, "Modus: VERBUNDEN (Test)", 11, 109, 278, GREEN);
#endif

  lv_obj_t *mem = card(p, 10, 217, 300, 125);
  systemHeap = label(mem, "Heap frei: --", 11, 10, 278, FG);
  systemPsram = label(mem, "PSRAM: --", 11, 38, 278, FG);
  systemUptime = label(mem, "Laufzeit: --", 11, 66, 278, MUTED);
  systemTouches = label(mem, "Touch-Aktionen: --", 11, 94, 278, MUTED);
}

static void buildChatPage(lv_obj_t *p) {
  label(p, "HERMES CHAT", 13, 13, 290, CYAN);
  lv_obj_t *cardChat = card(p, 10, 61, 300, 216);
  label(cardChat, "CHAT IST DEAKTIVIERT", 12, 23, 276, FG);
  label(cardChat, "Diese Ansicht ist nur ein Platzhalter.", 12, 62, 274, MUTED);
  label(cardChat, "Es werden keine Nachrichten", 12, 99, 274, MUTED);
  label(cardChat, "oder Befehle an Hermes gesendet.", 12, 121, 274, MUTED);
  label(cardChat, "Freigabe erst nach sicherem Transport", 12, 168, 274, GREEN);
  label(p, "Keine Schreibzugriffe auf den Pi", 13, 301, 290, MUTED);
}

static void buildUi() {
  lv_obj_t *screen = lv_scr_act();
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_style_bg_color(screen, lv_color_hex(BG), 0);
  lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
  label(screen, "HERMES TOUCH", 13, 10, 200, CYAN);
  label(screen, "v0.6  |  ONX3248G035", 13, 35, 280, MUTED);
  pages[0] = makePage(screen);
  pages[1] = makePage(screen);
  pages[2] = makePage(screen);
  pages[3] = makePage(screen);
  buildStatusPage(pages[0]);
  buildHistoryPage(pages[1]);
  buildSystemPage(pages[2]);
  buildChatPage(pages[3]);

  static const char *const titles[PAGE_COUNT] =
      {"STATUS", "GRAPH", "SYSTEM", "CHAT"};
  for (int i = 0; i < PAGE_COUNT; ++i) {
    navBtns[i] = lv_btn_create(screen);
    lv_obj_set_pos(navBtns[i], 5 + i * 79, 420);
    lv_obj_set_size(navBtns[i], 74, 51);
    styleButton(navBtns[i], 0x20334C);
    lv_obj_add_event_cb(navBtns[i], onNav, LV_EVENT_CLICKED, nullptr);
    lv_obj_t *txt = label(navBtns[i], titles[i], 0, 0, 68, FG);
    lv_obj_center(txt);
  }
  showPage(0);
}

static void updateLocalSystem() {
  if (systemHeap == nullptr) return;
  lv_label_set_text_fmt(systemHeap, "Heap frei: %lu KB",
                        (unsigned long)(ESP.getFreeHeap() / 1024));
  lv_label_set_text_fmt(systemPsram, "PSRAM: %lu / %lu KB frei",
                        (unsigned long)(ESP.getFreePsram() / 1024),
                        (unsigned long)(ESP.getPsramSize() / 1024));
  lv_label_set_text_fmt(systemUptime, "Laufzeit: %lu Minuten",
                        (unsigned long)(millis() / 60000));
  lv_label_set_text_fmt(systemTouches, "Touch-Aktionen: %lu",
                        (unsigned long)touchActions);
  lv_label_set_text_fmt(valueD, "%lu", (unsigned long)touchActions);
}

static void pushHistory(int32_t sample) {
  lv_chart_set_next_value(historyChart, historySeries, (lv_coord_t)sample);
  if (historySampleCount < GRAPH_SAMPLES) ++historySampleCount;
}

// LVGL 8.3's lv_label_set_text_fmt() does not enable %f by default.
// Convert floats to fixed-point digits using ONLY libc integer formatting;
// then pass the completed text to LVGL via its supported %s conversion.
static void decimalText(char *out, size_t cap, float value, uint8_t digits) {
  if (cap == 0) return;
  if (!std::isfinite(value) || fabsf(value) > 10000.0f ||
      (digits != 1 && digits != 2)) {
    snprintf(out, cap, "--");
    return;
  }
  const int32_t scale = digits == 1 ? 10 : 100;
  const int32_t scaled = (int32_t)lroundf(fabsf(value) * scale);
  const long whole = (long)(scaled / scale);
  const long fraction = (long)(scaled % scale);
  const char *sign = value < 0.0f ? "-" : "";
  snprintf(out, cap, "%s%ld.%0*ld", sign, whole, (int)digits, fraction);
}

static void sampleStatus() {
#if HT_DEMO_MODE
  const unsigned long heapKb = ESP.getFreeHeap() / 1024;
  const unsigned long psramKb = ESP.getPsramSize() / 1024;
  lv_label_set_text(statusHeadline, "OFFLINE-DEMO AKTIV");
  lv_label_set_text(statusDetail, "Hermes-Verbindung nicht aktiviert");
  lv_label_set_text_fmt(valueA, "%lu KB", heapKb);
  lv_label_set_text_fmt(valueB, "%lu KB", psramKb);
  lv_label_set_text_fmt(valueC, "%lu min", (unsigned long)(millis() / 60000));
  lv_label_set_text(statusFoot, "Quelle: ESP32, nicht Raspberry Pi");
  pushHistory((int32_t)heapKb);
  lv_label_set_text_fmt(historyValue, "Heap: %lu KB | %u/%u Werte", heapKb,
                        (unsigned)historySampleCount, (unsigned)GRAPH_SAMPLES);
#else
  if (WiFi.status() != WL_CONNECTED) {
    remoteValid = false;
    lv_label_set_text(statusHeadline, "WLAN NICHT VERBUNDEN");
    lv_label_set_text(statusDetail, "Pi-Daten momentan nicht verfuegbar");
  } else {
    // No cleartext fallback: require HTTPS, pinned local CA, and valid UTC.
    const String base = String(HT_BRIDGE_URL);
    const time_t utcNow = time(nullptr);
    if (!base.startsWith("https://") || strlen(HT_CA_CERT) < 100) {
      remoteValid = false;
      lv_label_set_text(statusHeadline, "TLS NICHT KONFIGURIERT");
      lv_label_set_text(statusDetail, "HTTPS-URL oder CA-Zertifikat fehlt");
    } else if (utcNow < 1767225600L) { // 2026-01-01 UTC
      remoteValid = false;
      lv_label_set_text(statusHeadline, "UHRZEIT NICHT SYNCHRON");
      lv_label_set_text(statusDetail, "Warte auf NTP fuer TLS-Pruefung");
    } else {
    WiFiClientSecure client;
    client.setCACert(HT_CA_CERT);
    HTTPClient http;
    const String url = base + "/v1/status";
    if (!http.begin(client, url)) {
      remoteValid = false;
      lv_label_set_text(statusHeadline, "BRIDGE-FEHLER");
      lv_label_set_text(statusDetail, "HTTP nicht initialisiert");
    } else {
      http.setConnectTimeout(4500);
      http.setTimeout(4500);
      http.addHeader("X-Hermes-Touch-Token", HT_DEVICE_TOKEN);
      const int code = http.GET();
      if (code == 200) {
        JsonDocument doc;
        DeserializationError error = deserializeJson(doc, http.getStream());
        if (!error && (doc["ok"] | false)) {
          remoteValid = true;
          apiHealthy = doc["hermes"]["api_healthy"] | false;
          dashboardAvailable = doc["hermes"]["dashboard_status_available"] | false;
          JsonVariant gw = doc["hermes"]["gateway_running"];
          gatewayKnown = !gw.isNull();
          gatewayRunning = gw.is<bool>() && gw.as<bool>();
          JsonVariant t = doc["system"]["cpu_temp_c"];
          JsonVariant r = doc["system"]["ram_used_pct"];
          JsonVariant l = doc["system"]["load1"];
          piTempKnown = !t.isNull();
          piRamKnown = !r.isNull();
          piLoadKnown = !l.isNull();
          if (piTempKnown) piTemp = t.as<float>();
          if (piRamKnown) piRam = r.as<float>();
          if (piLoadKnown) piLoad = l.as<float>();
        } else {
          remoteValid = false;
          lv_label_set_text(statusDetail, "Ungueltige JSON-Antwort");
        }
      } else {
        remoteValid = false;
        lv_label_set_text_fmt(statusDetail, "Bridge HTTP: %d", code);
      }
      http.end();
    }
    }
  }

  if (remoteValid) {
    lv_label_set_text(statusHeadline,
                      apiHealthy ? "HERMES-API ERREICHBAR" : "HERMES-API UNBEKANNT");
    lv_label_set_text_fmt(statusDetail, "Dashboard: %s | Gateway: %s",
                          dashboardAvailable ? "OK" : "--",
                          gatewayKnown ? (gatewayRunning ? "ON" : "OFF") : "--");
  } else {
    lv_label_set_text(statusHeadline, "KEINE AKTUELLEN PI-DATEN");
  }
  char numberText[24];
  if (remoteValid && piTempKnown) {
    decimalText(numberText, sizeof(numberText), piTemp, 1);
    lv_label_set_text_fmt(valueA, "%s C", numberText);
    pushHistory((int32_t)constrain((int)piTemp, 0, 100));
    lv_label_set_text_fmt(historyValue, "Pi: %s C | %u/%u Werte", numberText,
                          (unsigned)historySampleCount, (unsigned)GRAPH_SAMPLES);
  } else {
    lv_label_set_text(valueA, "--");
    lv_label_set_text(historyValue, "Keine gueltige Pi-Temperatur");
  }
  if (remoteValid && piRamKnown) {
    decimalText(numberText, sizeof(numberText), piRam, 1);
    lv_label_set_text_fmt(valueB, "%s %%", numberText);
  } else {
    lv_label_set_text(valueB, "--");
  }
  if (remoteValid && piLoadKnown) {
    decimalText(numberText, sizeof(numberText), piLoad, 2);
    lv_label_set_text(valueC, numberText);
  } else {
    lv_label_set_text(valueC, "--");
  }
  lv_label_set_text(statusFoot, remoteValid ? "Quelle: Raspberry Pi / Bridge" :
                                       "Quelle: Pi derzeit nicht erreichbar");
#endif
  updateLocalSystem();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(NEXTION_IIC_SDA_PIN, NEXTION_IIC_SCL_PIN, 400000);
  panelReset();
  gfx->begin(LCD_SPI_FREQ);
  gfx->setRotation(0);  // Verified on user's ONX3248G035
  gfx->fillScreen(RGB565_BLACK);
  pinMode(LCD_BL_PIN, OUTPUT);
  digitalWrite(LCD_BL_PIN, HIGH);
  if (!touch.begin(&Wire, CST826_ADDR))
    Serial.println("WARN: CST826 not initialized");

  lv_init();
  lv_disp_draw_buf_init(&drawBuf, dispBuf, nullptr, LCD_H_RES * BUF_LINES);
  lv_disp_drv_init(&dispDrv);
  dispDrv.hor_res = gfx->width();
  dispDrv.ver_res = gfx->height();
  dispDrv.flush_cb = flush;
  dispDrv.draw_buf = &drawBuf;
  lv_disp_drv_register(&dispDrv);
  static lv_indev_drv_t indev;
  lv_indev_drv_init(&indev);
  indev.type = LV_INDEV_TYPE_POINTER;
  indev.read_cb = touchRead;
  lv_indev_drv_register(&indev);
  buildUi();

#if HT_DEMO_MODE
  Serial.println("HERMES TOUCH v0.5 OFFLINE: NO WIFI / NO API / READ-ONLY");
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(HT_WIFI_SSID, HT_WIFI_PASSWORD);
  // TLS verification needs a valid device clock; do not bypass it.
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  lastWifiAttempt = millis();
#endif
  sampleStatus();
  lastSampleMs = millis();
}

void loop() {
  static uint32_t lastTick = millis();
  uint32_t now = millis();
  lv_tick_inc(now - lastTick);
  lastTick = now;
  lv_timer_handler();
#if !HT_DEMO_MODE
  if (WiFi.status() != WL_CONNECTED && now - lastWifiAttempt >= WIFI_RETRY_MS) {
    WiFi.reconnect();
    lastWifiAttempt = now;
  }
#endif
  if (requestSample || now - lastSampleMs >= SAMPLE_MS) {
    requestSample = false;
    lastSampleMs = now;
    sampleStatus();
  }
  delay(5);
}
