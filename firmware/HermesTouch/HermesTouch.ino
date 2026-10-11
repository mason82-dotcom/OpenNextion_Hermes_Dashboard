/* Hermes Touch v0.8.3 (candidate) - LOCAL-ONLY PTT PCM diagnostics.
 * Hardware: OpenNextion ONX3248G035 / ESP32-S3.
 * Default build has no Config.h -> NO WIFI, NO DEVICE TOKEN, NO API ACCESS.
 * Status and history explicitly distinguish local ESP32 demo values from Pi data.
 * No chat actions, no OTA, no Hermes agent configuration writes.
 */
#include <Arduino.h>
#include <esp_heap_caps.h>
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
// Microphone capture is a separate, explicitly opt-in LOCAL test.
// Without an explicit private Config.h switch, no mic driver is initialized.
#ifndef HT_MIC_TEST_ENABLED
#define HT_MIC_TEST_ENABLED 0
#endif
#if HT_MIC_TEST_ENABLED != 0 && HT_MIC_TEST_ENABLED != 1
#error "HT_MIC_TEST_ENABLED must be 0 or 1"
#endif
#if HT_MIC_TEST_ENABLED
#include "MicLevelWorker.h"
#endif

// Speaker output is an independent, deliberate LOCAL opt-in.
// It cannot play captured PCM, only a fixed, quiet 250ms test tone.
#ifndef HT_SPEAKER_TEST_ENABLED
#define HT_SPEAKER_TEST_ENABLED 0
#endif
#if HT_SPEAKER_TEST_ENABLED != 0 && HT_SPEAKER_TEST_ENABLED != 1
#error "HT_SPEAKER_TEST_ENABLED must be 0 or 1"
#endif
#if HT_SPEAKER_TEST_ENABLED
#include "SpeakerToneWorker.h"
#endif

#if !HT_DEMO_MODE
#include "TelemetryWorker.h"
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
// The PCF8574 writes the complete 8-bit GPIO byte on every operation.
// Only the GUI/setup task owns this state, including LCD reset and NS4168 amp.
static bool expanderAvailable = false;
static uint8_t expanderShadow = 0xFF;
#if HT_SPEAKER_TEST_ENABLED
static bool speakerAmpOn = false;
static bool speakerToneStartAttempted = false;
#endif
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
static lv_obj_t *connectionLabel = nullptr;
static lv_obj_t *chatMicLabel = nullptr;
static lv_obj_t *chatMicBar = nullptr;
static lv_obj_t *chatPttButton = nullptr;
static lv_obj_t *chatPttStatus = nullptr;
static lv_obj_t *chatPttProgress = nullptr;
static lv_obj_t *chatDiagPcm = nullptr;
static lv_obj_t *chatDiagRate = nullptr;
static lv_obj_t *chatDiagRms = nullptr;
static lv_obj_t *chatDiagPsram = nullptr;
static lv_obj_t *chatSpeakerButton = nullptr;
static lv_obj_t *chatSpeakerStatus = nullptr;
static lv_obj_t *historyChart = nullptr;
static lv_chart_series_t *historySeries = nullptr;
static lv_obj_t *historyValue = nullptr;
static lv_obj_t *systemHeap = nullptr;
static lv_obj_t *systemLargestBlock = nullptr;
static lv_obj_t *systemPsram = nullptr;
static lv_obj_t *systemStack = nullptr;
static lv_obj_t *systemUptime = nullptr;
static lv_obj_t *systemTouches = nullptr;
static uint32_t touchActions = 0;
static uint8_t historySampleCount = 0;
static uint32_t lastSampleMs = 0;
static bool requestSample = false;
static int activePage = 0;

#if !HT_DEMO_MODE
// GUI-owned cursor only. The network task never accesses UI or chart objects.
static uint32_t lastChartSequence = 0;
static bool telemetryStarted = false;
// GUI copy of the worker-reported minimum stack headroom in bytes.
static uint32_t displayedWorkerStackFreeBytes = 0;
static bool displayedWorkerStackObserved = false;
#endif

static void expanderSetPin(uint8_t pin, bool high) {
  if (!expanderAvailable) return;
  if (high) expanderShadow |= (uint8_t)(1U << pin);
  else expanderShadow &= (uint8_t)~(1U << pin);
  expander.digitalWriteByte(expanderShadow);
}

static void panelReset() {
  if (!expander.begin(PCF8574_ADDR, &Wire)) {
    Serial.println("WARN: PCF8574 not found");
    return;
  }
  expanderAvailable = true;
  // Speaker must always boot muted: PCF8574 P0 LOW = NS4168 disabled.
  // Keep LCD_RST (P6) independent; never toggle amplifier via reset writes.
  expanderShadow = (uint8_t)(0xFF & ~(1U << PCF8574_PIN_I2S_CTRL));
  expander.digitalWriteByte(expanderShadow);
  delay(20);
  expanderSetPin(PCF8574_PIN_LCD_RST, false);
  delay(120);
  expanderSetPin(PCF8574_PIN_LCD_RST, true);
  delay(120);
}

#if HT_SPEAKER_TEST_ENABLED
static void speakerAmpSet(bool enabled) {
  if (!expanderAvailable) return;
  if (speakerAmpOn == enabled) return;
  expanderSetPin(PCF8574_PIN_I2S_CTRL, enabled);
  speakerAmpOn = enabled;
}
#endif

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
#if HT_MIC_TEST_ENABLED
  // Leaving CHAT is another independent stop trigger for raw PTT capture.
  if (page != 3) micPttSetHeld(false);
#endif
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

static void onPttTouch(lv_event_t *event) {
#if HT_MIC_TEST_ENABLED
  const lv_event_code_t code = lv_event_get_code(event);
  // Mirror the official ONX3248G035 07_microphone_test touch lifecycle:
  // PRESSED -> start, LONG_PRESSED -> continue, RELEASED/PRESS_LOST -> stop.
  if (code == LV_EVENT_PRESSED && activePage == 3) {
    ++touchActions;
    micPttSetHeld(true);
  } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
    micPttSetHeld(false);
  }
#else
  (void)event;
#endif
}

static void onSpeakerTest(lv_event_t *event) {
#if HT_SPEAKER_TEST_ENABLED
  if (lv_event_get_code(event) != LV_EVENT_CLICKED) return;
  ++touchActions;
  (void)speakerToneRequest(); // local, fixed waveform; no network
#else
  (void)event;
#endif
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
  lv_obj_t *hw = card(p, 10, 49, 300, 130);
  label(hw, "OpenNextion ONX3248G035", 11, 12, 278, FG);
  label(hw, "ESP32-S3  |  ST7796U  |  CST826", 11, 43, 278, MUTED);
  label(hw, "320 x 480  |  LVGL 8.3", 11, 75, 278, MUTED);
#if HT_DEMO_MODE
  label(hw, "Modus: OFFLINE (kein WLAN)", 11, 101, 278, GREEN);
#else
  label(hw, "Modus: VERBUNDEN (Test)", 11, 101, 278, GREEN);
#endif

  // Six diagnostic rows fit without overlapping navigation (page ends at y=352).
  lv_obj_t *mem = card(p, 10, 186, 300, 156);
  systemHeap = label(mem, "Heap frei / Minimum: --", 11, 6, 278, FG);
  systemLargestBlock = label(mem, "Groesster Heap-Block: --", 11, 29, 278, FG);
  systemPsram = label(mem, "PSRAM: --", 11, 52, 278, FG);
  systemStack = label(mem, "TLS-Task Stackreserve: --", 11, 75, 278, MUTED);
  systemUptime = label(mem, "Laufzeit: --", 11, 98, 278, MUTED);
  systemTouches = label(mem, "Touch-Aktionen: --", 11, 121, 278, MUTED);
}

// Chat UI shell: no message send callback, transport, keyboard or API key.
static void buildChatPage(lv_obj_t *p) {
  label(p, "HERMES CHAT", 13, 12, 290, CYAN);
  label(p, "CHAT IST DEAKTIVIERT", 13, 36, 290, GREEN);

  lv_obj_t *chatHistory = lv_obj_create(p);
  lv_obj_set_pos(chatHistory, 10, 64);
  lv_obj_set_size(chatHistory, 300, 125);
  lv_obj_set_style_radius(chatHistory, 12, 0);
  lv_obj_set_style_bg_color(chatHistory, lv_color_hex(CARD), 0);
  lv_obj_set_style_bg_opa(chatHistory, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(chatHistory, 0, 0);
  lv_obj_set_style_pad_all(chatHistory, 0, 0);
  lv_obj_set_scroll_dir(chatHistory, LV_DIR_VER);
  // The scrollable (still empty) chat shell also hosts read-only, local
  // aggregate PCM diagnostics. Scroll down for the unchanged chat notice.
  label(chatHistory, "LOKALE AUDIO-DIAGNOSE", 13, 5, 270, CYAN);
#if HT_MIC_TEST_ENABLED
  chatDiagPcm = label(chatHistory, "PCM: -- | --.-s", 13, 30, 275, MUTED);
  chatDiagRate = label(chatHistory, "Rate: --/s | Anteil: --%", 13, 52, 275, MUTED);
  chatDiagRms = label(chatHistory, "RMS: -- Peak: -- Clip: --%", 13, 74, 275, MUTED);
  chatDiagPsram = label(chatHistory, "PSRAM KB: -- / -- / --", 13, 96, 275, MUTED);
#else
  label(chatHistory, "MIC/PTT: AUS (lokal)", 13, 48, 270, MUTED);
#endif
  // Scroll down below microphone diagnostics for the independent speaker test.
  chatSpeakerButton = lv_btn_create(chatHistory);
  lv_obj_set_pos(chatSpeakerButton, 13, 137);
  lv_obj_set_size(chatSpeakerButton, 135, 40);
  styleButton(chatSpeakerButton, 0x176A98);
#if HT_SPEAKER_TEST_ENABLED
  lv_obj_add_event_cb(chatSpeakerButton, onSpeakerTest, LV_EVENT_CLICKED, nullptr);
  chatSpeakerStatus = label(chatHistory, "SPK: STARTET", 155, 149, 127, MUTED);
#else
  lv_obj_add_state(chatSpeakerButton, LV_STATE_DISABLED);
  chatSpeakerStatus = label(chatHistory, "SPK: AUS", 155, 149, 127, MUTED);
#endif
  lv_obj_t *speakerText = label(chatSpeakerButton, "TESTTON", 0, 0, 114, FG);
  lv_obj_center(speakerText);
  label(chatHistory, "NOCH KEIN CHATVERLAUF", 13, 197, 270, FG);
  label(chatHistory, "Nachrichten nur nach Freigabe", 13, 225, 270, MUTED);
  label(chatHistory, "Keine Agent-Befehle oder", 13, 250, 270, GREEN);
  label(chatHistory, "Schreibzugriffe aktiviert.", 13, 273, 270, GREEN);

  // Local-only PTT. LVGL sets an atomic pressed flag, never handles audio.
  // Neither the button nor the disabled chat composer can send messages.
  chatPttButton = lv_btn_create(p);
  lv_obj_set_pos(chatPttButton, 10, 194);
  lv_obj_set_size(chatPttButton, 145, 39);
  styleButton(chatPttButton, 0x157EAD);
#if HT_MIC_TEST_ENABLED
  // Register exactly the lifecycle events used by OpenNextion's official
  // 07_microphone_test; do not dispatch unrelated LVGL events to PTT.
  lv_obj_add_event_cb(chatPttButton, onPttTouch, LV_EVENT_PRESSED, nullptr);
  lv_obj_add_event_cb(chatPttButton, onPttTouch, LV_EVENT_RELEASED, nullptr);
  lv_obj_add_event_cb(chatPttButton, onPttTouch, LV_EVENT_PRESS_LOST, nullptr);
  chatPttStatus = label(p, "PTT: BEREIT", 165, 204, 145, MUTED);
#else
  lv_obj_add_state(chatPttButton, LV_STATE_DISABLED);
  chatPttStatus = label(p, "PTT: AUS", 165, 204, 145, MUTED);
#endif
  lv_obj_t *pttText = label(chatPttButton, "HALTEN: TEST", 0, 0, 134, FG);
  lv_obj_center(pttText);
  chatPttProgress = lv_bar_create(chatPttButton);
  lv_obj_set_pos(chatPttProgress, 8, 32);
  lv_obj_set_size(chatPttProgress, 129, 4);
  lv_bar_set_range(chatPttProgress, 0, 4000);
  lv_bar_set_value(chatPttProgress, 0, LV_ANIM_OFF);
  lv_obj_set_style_bg_color(chatPttProgress, lv_color_hex(0x20334C), LV_PART_MAIN);
  lv_obj_set_style_bg_color(chatPttProgress, lv_color_hex(GREEN), LV_PART_INDICATOR);

  lv_obj_t *micCard = card(p, 10, 236, 300, 32);
#if HT_MIC_TEST_ENABLED
  chatMicLabel = label(micCard, "MIC: STARTET (lokal)", 8, 5, 166, MUTED);
#else
  chatMicLabel = label(micCard, "MIC: AUS (nur lokal)", 8, 5, 166, MUTED);
#endif
  chatMicBar = lv_bar_create(micCard);
  lv_obj_set_pos(chatMicBar, 182, 9);
  lv_obj_set_size(chatMicBar, 106, 14);
  lv_bar_set_range(chatMicBar, 0, 100);
  lv_bar_set_value(chatMicBar, 0, LV_ANIM_OFF);
  lv_obj_set_style_bg_color(chatMicBar, lv_color_hex(0x20334C), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(chatMicBar, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_set_style_bg_color(chatMicBar, lv_color_hex(GREEN), LV_PART_INDICATOR);

  // Disabled controls are deliberately styled to look disabled as well.
  lv_obj_t *chatInput = lv_textarea_create(p);
  lv_obj_set_pos(chatInput, 10, 273);
  lv_obj_set_size(chatInput, 215, 48);
  lv_textarea_set_one_line(chatInput, true);
  lv_textarea_set_placeholder_text(chatInput, "Nachricht (gesperrt)");
  lv_obj_add_state(chatInput, LV_STATE_DISABLED);
  lv_obj_set_style_bg_color(chatInput, lv_color_hex(0x24374D),
                            LV_PART_MAIN | LV_STATE_DISABLED);
  lv_obj_set_style_bg_opa(chatInput, LV_OPA_COVER,
                          LV_PART_MAIN | LV_STATE_DISABLED);
  lv_obj_set_style_text_color(chatInput, lv_color_hex(MUTED),
                              LV_PART_MAIN | LV_STATE_DISABLED);
  lv_obj_set_style_border_width(chatInput, 0,
                                LV_PART_MAIN | LV_STATE_DISABLED);

  lv_obj_t *chatSend = lv_btn_create(p);
  lv_obj_set_pos(chatSend, 233, 273);
  lv_obj_set_size(chatSend, 77, 48);
  styleButton(chatSend, 0x254A6D);
  lv_obj_add_state(chatSend, LV_STATE_DISABLED);
  lv_obj_set_style_bg_color(chatSend, lv_color_hex(0x20334C),
                            LV_PART_MAIN | LV_STATE_DISABLED);
  lv_obj_t *sendText = label(chatSend, "SENDEN", 0, 0, 68, MUTED);
  lv_obj_center(sendText);

  label(p, "NUR VORSCHAU / KEIN VERSAND", 13, 328, 290, MUTED);
}

// Read aggregate audio level only; always from the LVGL/main task.
static void updateMicUi() {
  if (chatMicLabel == nullptr || chatMicBar == nullptr) return;
#if HT_MIC_TEST_ENABLED
  MicLevelSnapshot mic;
  if (!micLevelRead(mic)) return;

  // Entire diagnostic panel is rendered from a snapshot copied on the GUI
  // task. No raw PCM or PSRAM pointer is ever visible to LVGL.
  if (chatPttProgress != nullptr) {
    const uint32_t elapsed = mic.pttDurationMs > MIC_PTT_MAX_MS
                                  ? MIC_PTT_MAX_MS : mic.pttDurationMs;
    lv_bar_set_value(chatPttProgress,
                     mic.pttPhase == MicPttPhase::RECORDING ||
                     mic.pttPhase == MicPttPhase::TIMEOUT ? elapsed : 0,
                     LV_ANIM_OFF);
  }
  if (chatDiagPcm != nullptr) {
    if (mic.pttPhase == MicPttPhase::ERROR ||
        mic.pttPhase == MicPttPhase::NO_PSRAM) {
      lv_label_set_text(chatDiagPcm, "PCM: FEHLER / KEIN PUFFER");
      lv_label_set_text(chatDiagRate, "Rate: --/s | Anteil: --%");
      lv_label_set_text(chatDiagRms, "RMS: -- Peak: -- Clip: --%");
      lv_label_set_text(chatDiagPsram, "PSRAM KB: -- / -- / --");
    } else {
      lv_label_set_text_fmt(chatDiagPcm, "PCM: %lu | %lu.%lus",
          (unsigned long)mic.pttSamples,
          (unsigned long)(mic.pttDurationMs / 1000),
          (unsigned long)((mic.pttDurationMs / 100) % 10));
      if (mic.pttDurationMs >= 200) {
        lv_label_set_text_fmt(chatDiagRate, "Rate: %lu/s | Anteil: %u%%",
            (unsigned long)mic.pttRateHz, (unsigned)mic.pttCoveragePct);
      } else {
        lv_label_set_text(chatDiagRate, "Rate: --/s | Anteil: --%");
      }
      lv_label_set_text_fmt(chatDiagRms, "RMS: %u Peak: %u Clip: %u%%",
          (unsigned)mic.pttRms, (unsigned)mic.pttPeak,
          (unsigned)mic.pttClipPct);
      if (mic.pttMemoryValid) {
        if (mic.pttPhase == MicPttPhase::RECORDING) {
          lv_label_set_text_fmt(chatDiagPsram,
              "PSRAM KB: %lu / %lu / --",
              (unsigned long)mic.pttPsramBeforeKB,
              (unsigned long)mic.pttPsramMinKB);
        } else {
          lv_label_set_text_fmt(chatDiagPsram,
              "PSRAM KB: %lu / %lu / %lu",
              (unsigned long)mic.pttPsramBeforeKB,
              (unsigned long)mic.pttPsramMinKB,
              (unsigned long)mic.pttPsramAfterKB);
        }
      } else {
        lv_label_set_text(chatDiagPsram, "PSRAM KB: -- / -- / --");
      }
    }
  }
  if (chatPttStatus != nullptr) {
    switch (mic.pttPhase) {
      case MicPttPhase::RECORDING:
        lv_label_set_text_fmt(chatPttStatus, "TEST: %lu.%lu/4s",
            (unsigned long)(mic.pttDurationMs / 1000),
            (unsigned long)((mic.pttDurationMs / 100) % 10));
        break;
      case MicPttPhase::DISCARDED:
        lv_label_set_text(chatPttStatus, "PTT: VERWORFEN");
        break;
      case MicPttPhase::TIMEOUT:
        lv_label_set_text(chatPttStatus, "PTT: LIMIT 4s");
        break;
      case MicPttPhase::NO_PSRAM:
        lv_label_set_text(chatPttStatus, "PTT: RAM FEHLT");
        break;
      case MicPttPhase::ERROR:
        lv_label_set_text(chatPttStatus, "PTT: FEHLER");
        break;
      default:
        lv_label_set_text(chatPttStatus, "PTT: BEREIT");
        break;
    }
  }
  if (mic.failed) {
    lv_label_set_text(chatMicLabel, "MIC: FEHLER (lokal)");
    lv_bar_set_value(chatMicBar, 0, LV_ANIM_OFF);
  } else if (mic.ready &&
             (uint32_t)(millis() - mic.lastSampleMs) <= MIC_VALID_AGE_MS) {
    lv_label_set_text_fmt(chatMicLabel, "MIC: %u %% (lokal)",
                          (unsigned)mic.levelPercent);
    lv_bar_set_value(chatMicBar, mic.levelPercent, LV_ANIM_OFF);
  } else {
    lv_label_set_text(chatMicLabel, "MIC: WARTE (lokal)");
    lv_bar_set_value(chatMicBar, 0, LV_ANIM_OFF);
  }
#endif
}

// Driven on the main/LVGL task. I2S writes are confined to the worker;
// the PCF8574 I2C amp-enable pin is never toggled by a FreeRTOS worker.
static void updateSpeakerUi() {
#if HT_SPEAKER_TEST_ENABLED
  SpeakerToneSnapshot output;
  if (!speakerToneRead(output)) return;
  // Force mute on startup, completion, errors or loss of the output worker.
  const bool desiredAmp =
      output.phase == SpeakerTonePhase::WAIT_AMP ||
      output.phase == SpeakerTonePhase::PLAYING;
  if (desiredAmp && expanderAvailable) {
    speakerAmpSet(true);
    speakerToneAmpAcknowledged(true);
  } else {
    speakerAmpSet(false);
    speakerToneAmpAcknowledged(false);
  }
  if (chatSpeakerStatus == nullptr) return;
  switch (output.phase) {
    case SpeakerTonePhase::READY:
      lv_label_set_text(chatSpeakerStatus, "SPK: BEREIT");
      break;
    case SpeakerTonePhase::QUEUED:
    case SpeakerTonePhase::WAIT_AMP:
      lv_label_set_text(chatSpeakerStatus, "SPK: STARTET");
      break;
    case SpeakerTonePhase::PLAYING:
      lv_label_set_text(chatSpeakerStatus, "SPK: TON");
      break;
    case SpeakerTonePhase::WAIT_MUTE:
      lv_label_set_text(chatSpeakerStatus, "SPK: STOPPT");
      break;
    case SpeakerTonePhase::DONE:
      lv_label_set_text_fmt(chatSpeakerStatus, "SPK: OK %lu",
          (unsigned long)output.completed);
      break;
    case SpeakerTonePhase::ERROR:
      lv_label_set_text(chatSpeakerStatus, "SPK: FEHLER");
      break;
    default:
      lv_label_set_text(chatSpeakerStatus, "SPK: STARTET");
      break;
  }
#endif
}

static void buildUi() {
  lv_obj_t *screen = lv_scr_act();
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_style_bg_color(screen, lv_color_hex(BG), 0);
  lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
  label(screen, "HERMES TOUCH", 13, 10, 200, CYAN);
  label(screen, "v0.8.3 | ONX3248G035", 13, 35, 280, MUTED);
#if !HT_DEMO_MODE
  connectionLabel = label(screen, "WLAN --", 219, 12, 97, MUTED);
#endif
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
  lv_label_set_text_fmt(systemHeap, "Heap: %lu KB | Min: %lu KB",
                        (unsigned long)(ESP.getFreeHeap() / 1024),
                        (unsigned long)(ESP.getMinFreeHeap() / 1024));
  lv_label_set_text_fmt(systemLargestBlock, "Groesster Block: %lu KB",
                        (unsigned long)(heap_caps_get_largest_free_block(
                            MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT) / 1024));
  lv_label_set_text_fmt(systemPsram, "PSRAM: %lu / %lu KB frei",
                        (unsigned long)(ESP.getFreePsram() / 1024),
                        (unsigned long)(ESP.getPsramSize() / 1024));
#if HT_DEMO_MODE
  lv_label_set_text(systemStack, "TLS-Task: OFFLINE");
#else
  if (displayedWorkerStackObserved)
    lv_label_set_text_fmt(systemStack, "TLS-Stack min. frei: %lu B",
                          (unsigned long)displayedWorkerStackFreeBytes);
  else
    lv_label_set_text(systemStack, "TLS-Stack min. frei: --");
#endif
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

// LVGL 8.3 label printf omits float formatting (%f) by default.
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
  // GUI only copies a short struct. Never performs WiFi, HTTPS, JSON or NTP.
  static TelemetrySnapshot latest;
  TelemetrySnapshot incoming;
  if (!telemetryStarted) latest.phase = TelemetryPhase::TASK_FAILED;
  else if (telemetryReadSnapshot(incoming)) {
    latest = incoming;
    // Last seen worker stack watermark, independent of Pi/TLS availability.
    displayedWorkerStackFreeBytes = incoming.workerStackMinFreeBytes;
    displayedWorkerStackObserved = true;
  }
  const uint32_t age = (uint32_t)(millis() - latest.lastSuccessMs);
  const bool fresh = latest.phase == TelemetryPhase::READY &&
                     latest.hasLastGood && age <= TELEMETRY_FRESH_MS;

  if (fresh) {
    lv_label_set_text(connectionLabel, "TLS OK");
    lv_label_set_text(statusHeadline, latest.apiHealthy ?
                      "HERMES-API ERREICHBAR" : "HERMES-API NICHT GESUND");
    lv_label_set_text_fmt(statusDetail, "Dashboard: %s | Gateway: %s",
                          latest.dashboardAvailable ? "OK" : "--",
                          latest.gatewayKnown ?
                            (latest.gatewayRunning ? "ON" : "OFF") : "--");
    lv_label_set_text_fmt(statusFoot, "Pi/TLS | vor %lu s",
                          (unsigned long)(age / 1000));
  } else {
    lv_label_set_text(connectionLabel, latest.wifiConnected ? "TLS --" : "WLAN --");
    switch (latest.phase) {
      case TelemetryPhase::WIFI_DOWN:
        lv_label_set_text(statusHeadline, "WLAN NICHT VERBUNDEN");
        lv_label_set_text(statusDetail, "Verbindung wird wiederholt");
        break;
      case TelemetryPhase::CLOCK_WAIT:
        lv_label_set_text(statusHeadline, "UHRZEIT NICHT SYNCHRON");
        lv_label_set_text(statusDetail, "Warte auf NTP fuer TLS");
        break;
      case TelemetryPhase::TLS_CONFIG:
        lv_label_set_text(statusHeadline, "TLS KONFIGURATION FEHLT");
        lv_label_set_text(statusDetail, "HTTPS-URL oder CA fehlt");
        break;
      case TelemetryPhase::HTTP_ERROR:
        lv_label_set_text(statusHeadline, "BRIDGE NICHT ERREICHBAR");
        lv_label_set_text_fmt(statusDetail, "HTTP/TLS: %d", latest.httpCode);
        break;
      case TelemetryPhase::JSON_ERROR:
        lv_label_set_text(statusHeadline, "STATUS NICHT LESBAR");
        lv_label_set_text(statusDetail, "Bridge JSON ungueltig");
        break;
      case TelemetryPhase::TASK_FAILED:
        lv_label_set_text(statusHeadline, "TELEMETRIE NICHT GESTARTET");
        lv_label_set_text(statusDetail, "Zu wenig Speicher fuer Task");
        break;
      case TelemetryPhase::READY:
        lv_label_set_text(statusHeadline, "PI DATEN VERALTET");
        lv_label_set_text(statusDetail, "Letzte Antwort zu alt");
        break;
      default:
        lv_label_set_text(statusHeadline, "VERBINDUNG WIRD GEPRUEFT");
        lv_label_set_text(statusDetail, "Pi/TLS wartet auf erste Messung");
        break;
    }
    if (latest.hasLastGood)
      lv_label_set_text_fmt(statusFoot, "Keine Livewerte | letzter OK: %lu s",
                            (unsigned long)(age / 1000));
    else
      lv_label_set_text(statusFoot, "Noch keine gueltigen Pi-Daten");
  }

  char numberText[24];
  if (fresh && latest.piTempKnown) {
    decimalText(numberText, sizeof(numberText), latest.piTemp, 1);
    lv_label_set_text_fmt(valueA, "%s C", numberText);
    // A GUI tick may run multiple times between network polls.
    // Append ONLY once per newly received successful sample.
    if (latest.sequence != lastChartSequence) {
      pushHistory((int32_t)constrain((int)latest.piTemp, 0, 100));
      lastChartSequence = latest.sequence;
    }
    lv_label_set_text_fmt(historyValue, "Pi: %s C | %u/%u Werte", numberText,
                          (unsigned)historySampleCount, (unsigned)GRAPH_SAMPLES);
  } else {
    lv_label_set_text(valueA, "--");
    lv_label_set_text(historyValue, "Keine aktuellen Pi-Temperaturwerte");
  }
  if (fresh && latest.piRamKnown) {
    decimalText(numberText, sizeof(numberText), latest.piRam, 1);
    lv_label_set_text_fmt(valueB, "%s %%", numberText);
  } else {
    lv_label_set_text(valueB, "--");
  }
  if (fresh && latest.piLoadKnown) {
    decimalText(numberText, sizeof(numberText), latest.piLoad, 2);
    lv_label_set_text(valueC, numberText);
  } else {
    lv_label_set_text(valueC, "--");
  }
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
  Serial.println("HERMES TOUCH v0.8.3 OFFLINE: NO WIFI / NO API / READ-ONLY");
#else
  // Creates a separate FreeRTOS network worker; LVGL never waits for HTTPS.
  telemetryStarted = telemetryStart();
  if (!telemetryStarted)
    Serial.println("WARN: Hermes telemetry worker could not start");
#endif
#if HT_MIC_TEST_ENABLED
  // Explicit opt-in only. No buffers or recordings leave the ESP32.
  if (!micLevelStart())
    Serial.println("WARN: local microphone level worker could not start");
#endif
#if HT_SPEAKER_TEST_ENABLED && !HT_MIC_TEST_ENABLED
  // With no mic enabled, I2S1 can initialize immediately.
  speakerToneStartAttempted = true;
  if (expanderAvailable && !speakerToneStart())
    Serial.println("WARN: local speaker tone worker could not start");
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
#if HT_MIC_TEST_ENABLED
  static uint32_t lastMicUiMs = 0;
  if ((uint32_t)(now - lastMicUiMs) >= 100) {
    lastMicUiMs = now;
    updateMicUi(); // only an aggregate read, never an I2S or HTTPS call
  }
#endif
#if HT_SPEAKER_TEST_ENABLED
#if HT_MIC_TEST_ENABLED
  // Arduino ESP_I2S uses I2S_NUM_AUTO. Wait until PDM RX has successfully
  // allocated its channel before reserving manufacturer's I2S1 for output.
  // Prevents a startup race and keeps the verified microphone operational.
  if (!speakerToneStartAttempted && expanderAvailable) {
    MicLevelSnapshot micForSpeaker;
    if (micLevelRead(micForSpeaker) &&
        (micForSpeaker.ready || micForSpeaker.failed)) {
      speakerToneStartAttempted = true;
      if (!speakerToneStart())
        Serial.println("WARN: local speaker tone worker could not start");
    }
  }
#endif
  static uint32_t lastSpeakerUiMs = 0;
  if ((uint32_t)(now - lastSpeakerUiMs) >= 20) {
    lastSpeakerUiMs = now;
    updateSpeakerUi(); // amp via main thread; worker handles I2S1 TX
  }
#endif
#if HT_DEMO_MODE
  if (requestSample || (uint32_t)(now - lastSampleMs) >= SAMPLE_MS) {
    requestSample = false;
    lastSampleMs = now;
    sampleStatus();
  }
#else
  if (requestSample) {
    requestSample = false;
    telemetryRequestRefresh(); // notify worker, never start HTTP in LVGL task
  }
  if ((uint32_t)(now - lastSampleMs) >= 1000) {
    lastSampleMs = now;
    sampleStatus(); // read synchronized snapshot and update labels/chart only
  }
#endif
  delay(5);
}
