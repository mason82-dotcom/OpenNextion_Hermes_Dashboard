#pragma once
// Hermes Touch quick-command chat client (opt-in HT_CHAT_QUICK_ENABLED).
// Runs ONLY on the telemetry FreeRTOS worker, never touches LVGL.
// The device sends nothing but the ID of a prompt that the Pi whitelisted;
// no free text, no keyboard, no Hermes API key on the ESP32.
// Answers are kept in RAM only (GUI history), never written to flash.
#include <Arduino.h>
#include <atomic>
#include <cstring>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

static constexpr uint8_t CHAT_MAX_PROMPTS = 6;
static constexpr size_t CHAT_ID_LEN = 17;     // Pi: ^[a-z0-9_]{1,16}$
static constexpr size_t CHAT_LABEL_LEN = 15;  // Pi: 1..14 ASCII characters
static constexpr size_t CHAT_ANSWER_LEN = 720; // Pi trims answers to 700
static constexpr uint32_t CHAT_POLL_MS = 2000;
static constexpr uint32_t CHAT_JOB_TIMEOUT_MS = 200000; // Pi upstream: 180 s
static constexpr uint32_t CHAT_PROMPT_RETRY_MS = 30000;

enum class ChatPhase : uint8_t {
  LOADING, UNAVAILABLE, READY, SENDING, RUNNING, DONE, FAILED
};

struct ChatSnapshot {
  ChatPhase phase = ChatPhase::LOADING;
  uint8_t promptCount = 0;
  uint32_t promptsVersion = 0;
  char promptIds[CHAT_MAX_PROMPTS][CHAT_ID_LEN] = {};
  char promptLabels[CHAT_MAX_PROMPTS][CHAT_LABEL_LEN] = {};
  int8_t activePrompt = -1;
  uint32_t answerSequence = 0;
  char answer[CHAT_ANSWER_LEN] = {};
  char error[24] = {};
};

static SemaphoreHandle_t chatMutex = nullptr;
static ChatSnapshot chatShared;
static ChatSnapshot chatWorkerState; // worker-only working copy
// GUI -> worker: index into the whitelisted prompt list, -1 = none.
static std::atomic<int8_t> chatRequested{-1};

static bool chatInit() {
  if (chatMutex == nullptr) chatMutex = xSemaphoreCreateMutex();
  return chatMutex != nullptr;
}

static void chatPublish() {
  if (chatMutex != nullptr &&
      xSemaphoreTake(chatMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
    chatShared = chatWorkerState;
    xSemaphoreGive(chatMutex);
  }
}

// GUI task: zero-wait copy; a busy mutex never stalls LVGL.
static bool chatReadSnapshot(ChatSnapshot &out) {
  if (chatMutex == nullptr || xSemaphoreTake(chatMutex, 0) != pdTRUE) return false;
  out = chatShared;
  xSemaphoreGive(chatMutex);
  return true;
}

static bool chatIsBusy(ChatPhase phase) {
  return phase == ChatPhase::SENDING || phase == ChatPhase::RUNNING;
}

static void chatSetError(const char *text) {
  chatWorkerState.phase = ChatPhase::FAILED;
  strlcpy(chatWorkerState.error, text, sizeof(chatWorkerState.error));
}

static const char *chatErrorText(const char *code) {
  if (strcmp(code, "timeout") == 0) return "ZEITLIMIT";
  if (strcmp(code, "auth") == 0) return "API-SCHLUESSEL";
  if (strcmp(code, "empty_answer") == 0) return "LEERE ANTWORT";
  return "HERMES-FEHLER";
}

static const char *chatHttpErrorText(int code) {
  switch (code) {
    case 400: return "ANFRAGE UNGUELTIG";
    case 403: return "CHAT AUF PI AUS";
    case 404: return "BEFEHL UNBEKANNT";
    case 409: return "PI BESCHAEFTIGT";
    case 429: return "LIMIT: WARTEN";
    default: return code < 0 ? "VERBINDUNG" : "BRIDGE-FEHLER";
  }
}

// One HTTPS request with the same trust rules as the status poll:
// local CA, IP SAN, NTP time, no redirects, no plaintext fallback.
static int chatHttp(const char *path, const char *body, JsonDocument &doc) {
  const String urlBase(HT_BRIDGE_URL);
  if (!urlBase.startsWith("https://")) return -1;
  WiFiClientSecure client;
  client.setCACert(HT_CA_CERT);
  HTTPClient http;
  if (!http.begin(client, urlBase + path)) return -1;
  http.setConnectTimeout(4500);
  http.setTimeout(6000);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.addHeader("X-Hermes-Touch-Token", HT_DEVICE_TOKEN);
  int code;
  if (body != nullptr) {
    http.addHeader("Content-Type", "application/json");
    code = http.POST(reinterpret_cast<uint8_t *>(const_cast<char *>(body)), strlen(body));
  } else {
    code = http.GET();
  }
  if (code == HTTP_CODE_OK || code == HTTP_CODE_ACCEPTED) {
    if (deserializeJson(doc, http.getStream(),
                        DeserializationOption::NestingLimit(4)))
      code = -2;
  }
  http.end();
  return code;
}

static void chatLoadPrompts() {
  JsonDocument doc;
  const int code = chatHttp("/v1/chat/prompts", nullptr, doc);
  if (code != HTTP_CODE_OK || !(doc["ok"] | false)) return; // retry later
  ChatSnapshot &s = chatWorkerState;
  s.promptCount = 0;
  if (doc["enabled"] | false) {
    for (JsonObject item : doc["prompts"].as<JsonArray>()) {
      if (s.promptCount >= CHAT_MAX_PROMPTS) break;
      const char *id = item["id"] | "";
      const char *label = item["label"] | "";
      if (*id == '\0' || *label == '\0' || strlen(id) >= CHAT_ID_LEN ||
          strlen(label) >= CHAT_LABEL_LEN) continue;
      strlcpy(s.promptIds[s.promptCount], id, CHAT_ID_LEN);
      strlcpy(s.promptLabels[s.promptCount], label, CHAT_LABEL_LEN);
      ++s.promptCount;
    }
  }
  s.phase = s.promptCount > 0 ? ChatPhase::READY : ChatPhase::UNAVAILABLE;
  ++s.promptsVersion;
}

// Called by the telemetry worker after each status poll.
static void chatService(bool linkReady) {
  static uint32_t lastPromptAttemptMs = 0;
  static uint32_t jobStartedMs = 0;
  static uint32_t lastPollMs = 0;
  static uint32_t job = 0;
  ChatSnapshot &s = chatWorkerState;
  if (!linkReady) return;
  const uint32_t now = millis();

  if ((s.phase == ChatPhase::LOADING || s.phase == ChatPhase::UNAVAILABLE) &&
      (lastPromptAttemptMs == 0 ||
       (uint32_t)(now - lastPromptAttemptMs) >= CHAT_PROMPT_RETRY_MS)) {
    lastPromptAttemptMs = now;
    chatLoadPrompts();
    chatPublish();
  }

  const int8_t requested = chatRequested.exchange(-1);
  if (requested >= 0 && requested < (int8_t)s.promptCount && !chatIsBusy(s.phase) &&
      s.phase != ChatPhase::LOADING && s.phase != ChatPhase::UNAVAILABLE) {
    s.phase = ChatPhase::SENDING;
    s.activePrompt = requested;
    s.error[0] = '\0';
    chatPublish();
    // The body carries only a whitelisted ID; the Pi re-validates it.
    char body[48];
    snprintf(body, sizeof(body), "{\"prompt_id\":\"%s\"}", s.promptIds[requested]);
    JsonDocument doc;
    const int code = chatHttp("/v1/chat/ask", body, doc);
    if (code == HTTP_CODE_ACCEPTED && (doc["job"] | 0u) > 0) {
      job = doc["job"] | 0u;
      s.phase = ChatPhase::RUNNING;
      jobStartedMs = millis();
      lastPollMs = 0;
    } else {
      chatSetError(chatHttpErrorText(code));
    }
    chatPublish();
  }

  if (s.phase == ChatPhase::RUNNING &&
      (lastPollMs == 0 || (uint32_t)(millis() - lastPollMs) >= CHAT_POLL_MS)) {
    lastPollMs = millis();
    JsonDocument doc;
    const int code = chatHttp("/v1/chat/state", nullptr, doc);
    if (code == HTTP_CODE_OK && (doc["job"] | 0u) == job) {
      const char *state = doc["state"] | "";
      if (strcmp(state, "done") == 0) {
        strlcpy(s.answer, doc["answer"] | "", sizeof(s.answer));
        s.phase = ChatPhase::DONE;
        ++s.answerSequence;
      } else if (strcmp(state, "error") == 0) {
        chatSetError(chatErrorText(doc["error"] | ""));
      }
    }
    if (s.phase == ChatPhase::RUNNING &&
        (uint32_t)(millis() - jobStartedMs) >= CHAT_JOB_TIMEOUT_MS)
      chatSetError("ZEITLIMIT");
    chatPublish();
  }
}

// GUI task: request one whitelisted prompt and wake the network worker.
static void chatRequestPrompt(int8_t slot, TaskHandle_t worker) {
  if (slot < 0 || slot >= (int8_t)CHAT_MAX_PROMPTS) return;
  chatRequested.store(slot);
  if (worker != nullptr) xTaskNotifyGive(worker);
}
