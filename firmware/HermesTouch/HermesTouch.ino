/* Hermes Touch 0.2. Read-only status UI for OpenNextion ONX3248G035.
 * Board bring-up based on official OpenNextion Arduino 09_outofbox_demo.
 * No OTA, no Hermes commands, no chat enablement.
 */
#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Arduino_GFX_Library.h>
#include <Adafruit_CST8XX.h>
#include <Adafruit_PCF8574.h>
#define LV_CONF_SKIP
#include <lvgl.h>
#include "BoardConfig.h"
#include "Config.h"

static constexpr uint32_t STATUS_INTERVAL_MS = 5000;
static constexpr uint32_t WIFI_RETRY_MS = 15000;
static constexpr uint32_t LCD_SPI_FREQ = 80000000;
static constexpr uint16_t LVGL_BUF_LINES = 40;
Arduino_DataBus *bus = new Arduino_HWSPI(
    LCD_DC_PIN, LCD_CS_PIN, LCD_SCLK_PIN, LCD_MOSI_PIN, LCD_MISO_PIN, &SPI, true);
Arduino_GFX *gfx = new Arduino_ST7796(
    bus, GFX_NOT_DEFINED, 0, false, LCD_H_RES, LCD_V_RES);
Adafruit_CST8XX touch;
Adafruit_PCF8574 expander;
static lv_disp_draw_buf_t drawBuf;
static lv_disp_drv_t dispDrv;
static lv_color_t dispBuf[LCD_H_RES * LVGL_BUF_LINES];
static lv_obj_t *infoLabel;
static lv_obj_t *hermesLabel;
static lv_obj_t *apiLabel;
static lv_obj_t *tempLabel;
static lv_obj_t *ramLabel;
static lv_obj_t *loadLabel;
static uint32_t lastRefresh = 0;
static uint32_t lastWifiAttempt = 0;
static bool refreshRequested = false;

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
  static int16_t x = 0, y = 0;
  if (touch.touched()) {
    auto point = touch.getPoint();
    x = constrain(point.x, 0, (int16_t)gfx->width() - 1);
    y = constrain(point.y, 0, (int16_t)gfx->height() - 1);
    data->state = LV_INDEV_STATE_PR;
  } else {
    data->state = LV_INDEV_STATE_REL;
  }
  data->point.x = x;
  data->point.y = y;
}

static lv_obj_t *makeLabel(lv_obj_t *parent, const char *text, int x, int y, uint32_t color) {
  lv_obj_t *label = lv_label_create(parent);
  lv_obj_set_width(label, 284);
  lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
  lv_obj_set_pos(label, x, y);
  lv_label_set_text(label, text);
  return label;
}

static void requestRefresh(lv_event_t *event) {
  if (lv_event_get_code(event) == LV_EVENT_CLICKED) refreshRequested = true;
}

static void buildUi() {
  lv_obj_t *scr = lv_scr_act();
  lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_style_bg_color(scr, lv_color_hex(0x101827), 0);
  lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
  makeLabel(scr, "HERMES TOUCH  |  0.2", 14, 15, 0x88caff);
  makeLabel(scr, "RASPBERRY PI 5  /  LIVE STATUS", 14, 64, 0x9fb2c8);
  infoLabel = makeLabel(scr, "WLAN verbindet ...", 14, 105, 0xffffff);
  hermesLabel = makeLabel(scr, "Hermes-Dashboard: unbekannt", 14, 158, 0x86d9b6);
  apiLabel = makeLabel(scr, "Hermes-API: unbekannt", 14, 201, 0x86d9b6);
  tempLabel = makeLabel(scr, "CPU-Temperatur: --", 14, 236, 0xffffff);
  ramLabel = makeLabel(scr, "RAM-Belegung: --", 14, 286, 0xffffff);
  loadLabel = makeLabel(scr, "Systemlast: --", 14, 336, 0xffffff);
  lv_obj_t *refreshBtn = lv_btn_create(scr);
  lv_obj_set_size(refreshBtn, 146, 40);
  lv_obj_set_pos(refreshBtn, 14, 392);
  lv_obj_add_event_cb(refreshBtn, requestRefresh, LV_EVENT_CLICKED, nullptr);
  lv_obj_t *refreshText = lv_label_create(refreshBtn);
  lv_label_set_text(refreshText, "Aktualisieren");
  lv_obj_center(refreshText);
  makeLabel(scr, "STATUS-MODUS  /  CHAT GESPERRT", 14, 437, 0x9fb2c8);
}

static void statusRefresh() {
  if (WiFi.status() != WL_CONNECTED) {
    lv_label_set_text(infoLabel, "WLAN: getrennt");
    lv_label_set_text(hermesLabel, "Bridge nicht erreichbar");
    lv_label_set_text(apiLabel, "Hermes-API: unbekannt");
    lv_label_set_text(tempLabel, "CPU-Temperatur: --");
    lv_label_set_text(ramLabel, "RAM-Belegung: --");
    lv_label_set_text(loadLabel, "Systemlast: --");
    return;
  }
  String url = String(HT_BRIDGE_URL) + "/v1/status";
  WiFiClient client;
  HTTPClient http;
  if (!http.begin(client, url)) {
    lv_label_set_text(hermesLabel, "HTTP-Initialisierung fehlgeschlagen");
    return;
  }
  http.setTimeout(1200);
  http.addHeader("X-Hermes-Touch-Token", HT_DEVICE_TOKEN);
  int code = http.GET();
  String body = code == 200 ? http.getString() : "";
  http.end();
  lv_label_set_text_fmt(infoLabel, "WLAN: %s", WiFi.localIP().toString().c_str());
  if (code != 200) {
    lv_label_set_text_fmt(hermesLabel, "Bridge HTTP: %d", code);
    lv_label_set_text(apiLabel, "Hermes-API: unbekannt");
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    lv_label_set_text(hermesLabel, "Bridge: ungueltiges JSON");
    lv_label_set_text(apiLabel, "Hermes-API: unbekannt");
    return;
  }
  bool dashboard = doc["hermes"]["dashboard_reachable"] | false;
  bool apiHealthy = doc["hermes"]["api_healthy"] | false;
  lv_label_set_text(apiLabel, apiHealthy ? "Hermes-API: gesund" : "Hermes-API: nicht erreichbar");
  lv_label_set_text(hermesLabel, dashboard ? "Hermes-Dashboard: erreichbar" :
                                      "Dashboard: offline / unbekannt");
  JsonVariant t = doc["system"]["cpu_temp_c"];
  JsonVariant r = doc["system"]["ram_used_pct"];
  JsonVariant l = doc["system"]["load1"];
  if (!t.isNull()) lv_label_set_text_fmt(tempLabel, "CPU-Temperatur: %.1f C", t.as<float>());
  else lv_label_set_text(tempLabel, "CPU-Temperatur: --");
  if (!r.isNull()) lv_label_set_text_fmt(ramLabel, "RAM-Belegung: %.1f %%", r.as<float>());
  else lv_label_set_text(ramLabel, "RAM-Belegung: --");
  if (!l.isNull()) lv_label_set_text_fmt(loadLabel, "Systemlast: %.2f", l.as<float>());
  else lv_label_set_text(loadLabel, "Systemlast: --");
}

void setup() {
  Serial.begin(115200);
  Wire.begin(NEXTION_IIC_SDA_PIN, NEXTION_IIC_SCL_PIN, 400000);
  panelReset();
  gfx->begin(LCD_SPI_FREQ);
  gfx->setRotation(0);  // same transform as official LVGL out-of-box example
  gfx->fillScreen(RGB565_BLACK);
  pinMode(LCD_BL_PIN, OUTPUT);
  digitalWrite(LCD_BL_PIN, HIGH);
  if (!touch.begin(&Wire, CST826_ADDR)) Serial.println("WARN: CST826 not initialized");
  lv_init();
  lv_disp_draw_buf_init(&drawBuf, dispBuf, nullptr, LCD_H_RES * LVGL_BUF_LINES);
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
  WiFi.mode(WIFI_STA);
  WiFi.begin(HT_WIFI_SSID, HT_WIFI_PASSWORD);
  lastWifiAttempt = millis();
}

void loop() {
  static uint32_t lastTick = millis();
  uint32_t now = millis();
  lv_tick_inc(now - lastTick);
  lastTick = now;
  lv_timer_handler();
  if (WiFi.status() != WL_CONNECTED && now - lastWifiAttempt >= WIFI_RETRY_MS) {
    WiFi.reconnect();
    lastWifiAttempt = now;
  }
  if (refreshRequested || now - lastRefresh >= STATUS_INTERVAL_MS) {
    refreshRequested = false;
    lastRefresh = now;
    statusRefresh();
  }
  delay(5);
}
