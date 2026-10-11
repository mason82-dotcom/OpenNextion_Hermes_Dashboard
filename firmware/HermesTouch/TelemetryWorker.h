#pragma once
// Hermes Touch v0.7: connected-mode background-only HTTPS status retrieval.
// Included exclusively when HT_DEMO_MODE==0 and Config.h/LocalCa.h exist.
// Worker NEVER touches LVGL objects or the LCD/touch drivers.
#include <Arduino.h>
#include <cmath>
#include <time.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include "LocalCa.h"
#ifndef HT_CHAT_QUICK_ENABLED
#define HT_CHAT_QUICK_ENABLED 0
#endif
#if HT_CHAT_QUICK_ENABLED
#include "ChatWorker.h" // whitelisted quick commands, same worker and trust
#endif

enum class TelemetryPhase : uint8_t {
  STARTING, WIFI_DOWN, CLOCK_WAIT, TLS_CONFIG, HTTP_ERROR, JSON_ERROR,
  READY, TASK_FAILED
};

struct TelemetrySnapshot {
  TelemetryPhase phase = TelemetryPhase::STARTING;
  bool wifiConnected = false;
  int httpCode = 0;
  bool hasLastGood = false;
  uint32_t lastSuccessMs = 0;
  uint32_t sequence = 0;
  // ESP-IDF FreeRTOS high-water mark: minimum remaining stack in bytes.
  // Measured inside the worker; never read its task state from LVGL.
  uint32_t workerStackMinFreeBytes = 0;
  bool apiHealthy = false;
  bool dashboardAvailable = false;
  bool gatewayKnown = false;
  bool gatewayRunning = false;
  bool piTempKnown = false;
  bool piRamKnown = false;
  bool piLoadKnown = false;
  float piTemp = 0.0f;
  float piRam = 0.0f;
  float piLoad = 0.0f;
};

static constexpr uint32_t TELEMETRY_PERIOD_MS = 5000;
static constexpr uint32_t WIFI_RETRY_MS = 15000;
static constexpr uint32_t TELEMETRY_FRESH_MS = 15000;
static SemaphoreHandle_t telemetryMutex = nullptr;
static TaskHandle_t telemetryTaskHandle = nullptr;
static TelemetrySnapshot telemetryShared;

// All shared access is a SHORT in-RAM copy under a mutex.
// GUI snapshot reads have zero wait, even during TLS handshake or WiFi failure.
static void telemetryPublish(const TelemetrySnapshot &snapshot) {
  if (telemetryMutex != nullptr &&
      xSemaphoreTake(telemetryMutex, portMAX_DELAY) == pdTRUE) {
    telemetryShared = snapshot;
    xSemaphoreGive(telemetryMutex);
  }
}

static bool telemetryReadSnapshot(TelemetrySnapshot &out) {
  if (telemetryMutex == nullptr ||
      xSemaphoreTake(telemetryMutex, 0) != pdTRUE) return false;
  out = telemetryShared;
  xSemaphoreGive(telemetryMutex);
  return true;
}

// The following function is called on the FreeRTOS network worker ONLY.
static void telemetryPoll(TelemetrySnapshot &snapshot) {
  snapshot.wifiConnected = WiFi.status() == WL_CONNECTED;
  snapshot.httpCode = 0;
  if (!snapshot.wifiConnected) {
    snapshot.phase = TelemetryPhase::WIFI_DOWN;
    return;
  }

  // Do not fall back to plaintext HTTP, even on TLS errors.
  const String urlBase(HT_BRIDGE_URL);
  if (!urlBase.startsWith("https://") || strlen(HT_CA_CERT) < 100) {
    snapshot.phase = TelemetryPhase::TLS_CONFIG;
    return;
  }
  if (time(nullptr) < 1767225600L) { // 2026-01-01 UTC
    snapshot.phase = TelemetryPhase::CLOCK_WAIT;
    return;
  }

  WiFiClientSecure client;
  client.setCACert(HT_CA_CERT); // CA chain, server IP SAN and expiry verified
  HTTPClient http;
  if (!http.begin(client, urlBase + "/v1/status")) {
    snapshot.phase = TelemetryPhase::HTTP_ERROR;
    return;
  }
  http.setConnectTimeout(4500);
  http.setTimeout(4500);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.addHeader("X-Hermes-Touch-Token", HT_DEVICE_TOKEN);
  const int result = http.GET();
  snapshot.httpCode = result;
  if (result != HTTP_CODE_OK) {
    snapshot.phase = TelemetryPhase::HTTP_ERROR;
    http.end();
    return;
  }

  JsonDocument doc;
  const DeserializationError parseError = deserializeJson(
      doc, http.getStream(), DeserializationOption::NestingLimit(8));
  http.end();
  if (parseError || !(doc["ok"] | false) || (doc["schema_version"] | 0) != 1) {
    snapshot.phase = TelemetryPhase::JSON_ERROR;
    return;
  }

  // Clear validity on each successful payload; never reuse a previous value
  // when a new JSON payload has null/missing/invalid fields.
  snapshot.apiHealthy = doc["hermes"]["api_healthy"] | false;
  snapshot.dashboardAvailable = doc["hermes"]["dashboard_status_available"] | false;
  JsonVariant gw = doc["hermes"]["gateway_running"];
  snapshot.gatewayKnown = gw.is<bool>();
  snapshot.gatewayRunning = snapshot.gatewayKnown && gw.as<bool>();

  JsonVariant t = doc["system"]["cpu_temp_c"];
  JsonVariant r = doc["system"]["ram_used_pct"];
  JsonVariant l = doc["system"]["load1"];
  const float temp = t.as<float>();
  const float ram = r.as<float>();
  const float load = l.as<float>();
  snapshot.piTempKnown = !t.isNull() && std::isfinite(temp) && temp >= -20.0f && temp <= 150.0f;
  snapshot.piRamKnown = !r.isNull() && std::isfinite(ram) && ram >= 0.0f && ram <= 100.0f;
  snapshot.piLoadKnown = !l.isNull() && std::isfinite(load) && load >= 0.0f && load < 1000.0f;
  snapshot.piTemp = snapshot.piTempKnown ? temp : 0.0f;
  snapshot.piRam = snapshot.piRamKnown ? ram : 0.0f;
  snapshot.piLoad = snapshot.piLoadKnown ? load : 0.0f;

  snapshot.phase = TelemetryPhase::READY;
  snapshot.hasLastGood = true;
  snapshot.lastSuccessMs = millis();
  ++snapshot.sequence;
}

static void telemetryTask(void *) {
  TelemetrySnapshot snapshot;
  WiFi.mode(WIFI_STA);
  WiFi.begin(HT_WIFI_SSID, HT_WIFI_PASSWORD);
  // TLS requires trusted UTC time; synchronizing is separate from GUI.
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t lastWiFiAttempt = millis();

  for (;;) {
    if (WiFi.status() != WL_CONNECTED &&
        (uint32_t)(millis() - lastWiFiAttempt) >= WIFI_RETRY_MS) {
      WiFi.reconnect();
      lastWiFiAttempt = millis();
    }
    telemetryPoll(snapshot);
    // ESP-IDF reports task stack high-water mark in BYTES, not words.
    // Query from this task only, after the potentially stack-heavy TLS poll.
    snapshot.workerStackMinFreeBytes = (uint32_t)uxTaskGetStackHighWaterMark(nullptr);
    telemetryPublish(snapshot);
#if HT_CHAT_QUICK_ENABLED
    // Sequential on this task: never two TLS sessions at the same time.
    chatService(snapshot.phase == TelemetryPhase::READY);
    const uint32_t waitMs = chatIsBusy(chatWorkerState.phase)
                                ? CHAT_POLL_MS : TELEMETRY_PERIOD_MS;
#else
    const uint32_t waitMs = TELEMETRY_PERIOD_MS;
#endif
    // The LVGL thread may wake the worker immediately after a touch.
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(waitMs));
  }
}

static bool telemetryStart() {
  telemetryMutex = xSemaphoreCreateMutex();
  if (telemetryMutex == nullptr) return false;
#if HT_CHAT_QUICK_ENABLED
  if (!chatInit()) return false;
#endif
  const BaseType_t started = xTaskCreate(telemetryTask, "hermes-tls",
                                         14336, nullptr, 1, &telemetryTaskHandle);
  if (started != pdPASS) {
    telemetryTaskHandle = nullptr;
    TelemetrySnapshot failed;
    failed.phase = TelemetryPhase::TASK_FAILED;
    telemetryPublish(failed);
    return false;
  }
  return true;
}

static void telemetryRequestRefresh() {
  if (telemetryTaskHandle != nullptr) xTaskNotifyGive(telemetryTaskHandle);
}
