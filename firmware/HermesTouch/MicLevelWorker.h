#pragma once
// Optional LOCAL-ONLY PDM meter and bounded push-to-talk test (ESP32-S3).
// PTT raw PCM stays temporarily in PSRAM while held; overwritten and freed
// on release/timeout. NO file, HTTP, WiFi, agent actions, or LVGL calls.
// Only aggregate level and PTT state cross the mutex to the GUI.
// Hardware: MIC_PDM CLK GPIO19, DATA GPIO20, Arduino-ESP32 core 3.3.2 ESP_I2S.
#include <Arduino.h>
#include <ESP_I2S.h>
#include <esp_heap_caps.h>
#include <atomic>
#include <cstring>
#include <math.h>
#include "BoardConfig.h"
#include "MicAudioMetrics.h"

static constexpr uint32_t MIC_SAMPLE_RATE = 16000;
static constexpr size_t MIC_PCM_SAMPLES = 256;
static constexpr uint32_t MIC_SAMPLE_TIMEOUT_MS = 150;
static constexpr uint32_t MIC_VALID_AGE_MS = 1500;
// Strict RAM bound: 16 kHz mono 16-bit x 4 sec = 128,000 bytes PSRAM.
// Reserve only while touch is held. Never retain PCM after stopping.
static constexpr uint32_t MIC_PTT_MAX_MS = 4000;
static constexpr size_t MIC_PTT_MAX_SAMPLES =
    MIC_SAMPLE_RATE * MIC_PTT_MAX_MS / 1000;
static_assert(MIC_PTT_MAX_SAMPLES * sizeof(int16_t) == 128000,
              "PTT buffer must remain bounded at 128 KB");
enum class MicPttPhase : uint8_t {
  READY, RECORDING, DISCARDED, TIMEOUT, NO_PSRAM, ERROR
};

struct MicLevelSnapshot {
  bool ready = false;
  bool failed = false;
  uint8_t levelPercent = 0; // relative amplitude, not calibrated sound pressure
  uint32_t lastSampleMs = 0;
  MicPttPhase pttPhase = MicPttPhase::READY;
  uint32_t pttDurationMs = 0;
  uint32_t pttSamples = 0; // only a count, never a PCM pointer
  // Aggregate diagnostics only; NEVER a recording, PCM pointer or waveform.
  uint16_t pttRms = 0;
  uint16_t pttPeak = 0;
  uint8_t pttClipPct = 0;
  uint32_t pttRateHz = 0; // observed buffer-fill throughput, not I2S clock
  uint8_t pttCoveragePct = 0; // approximate share of expected 16k samples
  bool pttMemoryValid = false;
  uint32_t pttPsramBeforeKB = 0;
  uint32_t pttPsramMinKB = 0;
  uint32_t pttPsramAfterKB = 0;
};

static SemaphoreHandle_t micLevelMutex = nullptr;
static MicLevelSnapshot micLevelShared;
static I2SClass micLevelI2S;
// LVGL button changes only this atomic boolean, never the audio driver.
static std::atomic<bool> micPttHeld{false};

static void micPttSetHeld(bool held) {
  micPttHeld.store(held, std::memory_order_release);
}

// Worker-only: overwrite all populated PCM samples before freeing PSRAM.
static void micPttDiscard(int16_t *&audio, size_t usedSamples) {
  if (audio == nullptr) return;
  volatile uint8_t *dest = reinterpret_cast<volatile uint8_t *>(audio);
  const size_t count = usedSamples * sizeof(int16_t);
  for (size_t i = 0; i < count; ++i) dest[i] = 0;
  heap_caps_free(audio);
  audio = nullptr;
}

static void micLevelPublish(const MicLevelSnapshot &sample) {
  if (micLevelMutex != nullptr &&
      xSemaphoreTake(micLevelMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
    micLevelShared = sample;
    xSemaphoreGive(micLevelMutex);
  }
}

// Called ONLY by the GUI task; a busy mutex must never stall LVGL.
static bool micLevelRead(MicLevelSnapshot &out) {
  if (micLevelMutex == nullptr ||
      xSemaphoreTake(micLevelMutex, 0) != pdTRUE) return false;
  out = micLevelShared;
  xSemaphoreGive(micLevelMutex);
  return true;
}

static void micLevelTask(void *) {
  micLevelI2S.setPinsPdmRx(MIC_PDM_CLK_PIN, MIC_PDM_DATA_PIN);
  if (!micLevelI2S.begin(I2S_MODE_PDM_RX, MIC_SAMPLE_RATE,
                        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    MicLevelSnapshot failed;
    failed.failed = true;
    failed.pttPhase = MicPttPhase::ERROR;
    micLevelPublish(failed);
    micLevelI2S.end();
    vTaskDelete(nullptr);
    return;
  }
  micLevelI2S.setTimeout(MIC_SAMPLE_TIMEOUT_MS);

  int16_t pcm[MIC_PCM_SAMPLES];
  uint8_t failedReads = 0;
  int16_t *pttAudio = nullptr; // worker-exclusive; never published
  size_t pttSamples = 0;
  uint32_t pttStartedMs = 0;
  bool pttArmed = true; // timeout cannot restart until physical release
  MicPttPhase pttPhase = MicPttPhase::READY;
  uint32_t pttDurationMs = 0;
  uint32_t pttLastSamples = 0;
  MicAudioMetrics pttMetrics; // worker-only aggregates; no raw PCM here
  uint32_t pttPsramBeforeBytes = 0;
  uint32_t pttPsramMinBytes = 0;
  uint32_t pttPsramAfterBytes = 0;
  bool pttMemoryValid = false;
  for (;;) {
    const uint32_t startLoopMs = millis();
    const bool held = micPttHeld.load(std::memory_order_acquire);
    if (!held) pttArmed = true;
    // End promptly without waiting for an additional I2S read. Elapsed-time
    // enforcement is independent from LVGL or how many samples arrive.
    if (pttAudio != nullptr &&
        (!held || (uint32_t)(startLoopMs - pttStartedMs) >= MIC_PTT_MAX_MS)) {
      const bool expired =
          (uint32_t)(startLoopMs - pttStartedMs) >= MIC_PTT_MAX_MS;
      pttDurationMs = min((uint32_t)(startLoopMs - pttStartedMs),
                          MIC_PTT_MAX_MS);
      pttLastSamples = (uint32_t)pttSamples;
      micPttDiscard(pttAudio, pttSamples);
      pttPsramAfterBytes = ESP.getFreePsram();
      pttSamples = 0;
      pttPhase = expired ? MicPttPhase::TIMEOUT : MicPttPhase::DISCARDED;
      pttArmed = !held;
    }
    if (pttAudio == nullptr && held && pttArmed && failedReads == 0) {
      pttArmed = false;
      // Manufacturer 07_microphone_test also buffers in PSRAM. We never
      // fall back to internal heap, and measure memory before allocation.
      pttPsramBeforeBytes = ESP.getFreePsram();
      pttAudio = static_cast<int16_t *>(heap_caps_malloc(
          MIC_PTT_MAX_SAMPLES * sizeof(int16_t),
          MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
      if (pttAudio == nullptr) {
        pttPhase = MicPttPhase::NO_PSRAM;
        pttDurationMs = 0;
        pttLastSamples = 0;
        pttMemoryValid = false;
        pttMetrics = MicAudioMetrics{};
      } else {
        pttStartedMs = startLoopMs;
        pttSamples = 0;
        pttLastSamples = 0;
        pttDurationMs = 0;
        pttMetrics = MicAudioMetrics{};
        pttMemoryValid = true;
        pttPsramMinBytes = ESP.getFreePsram();
        pttPsramAfterBytes = 0; // "after" unavailable while recording
        pttPhase = MicPttPhase::RECORDING;
      }
    }
    // ESP_I2S readBytes() runs ONLY inside this separate FreeRTOS task.
    // A small scratch PCM buffer is erased every cycle; when the local PTT
    // button is held, at most four seconds are temporarily copied to PSRAM.
    const size_t got = micLevelI2S.readBytes(
        reinterpret_cast<char *>(pcm), sizeof(pcm));
    if (got < sizeof(int16_t) * 32 || (got % sizeof(int16_t)) != 0) {
      if (failedReads < 3) ++failedReads;
      if (failedReads >= 3) {
        // Read failure must discard previously buffered audio too.
        micPttDiscard(pttAudio, pttSamples);
        pttPsramAfterBytes = ESP.getFreePsram();
        pttSamples = 0;
        pttArmed = false; // require finger release before trying again
        pttPhase = MicPttPhase::ERROR;
        MicLevelSnapshot failed;
        failed.failed = true;
        failed.pttPhase = pttPhase;
        failed.pttSamples = pttLastSamples;
        failed.pttDurationMs = pttDurationMs;
        failed.pttRms = micMetricsRms(pttMetrics);
        failed.pttPeak = pttMetrics.peak;
        failed.pttClipPct = micMetricsClippedPercent(pttMetrics);
        micLevelPublish(failed);
      }
      // Clear samples even when an I2S read was partial/failed.
      memset(pcm, 0, sizeof(pcm));
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }
    failedReads = 0;
    const size_t count = got / sizeof(int16_t);
    uint64_t energy = 0;
    for (size_t i = 0; i < count; ++i) {
      const int32_t value = (int32_t)pcm[i];
      energy += (uint64_t)(value * value);
    }
    // Relative VU scale only: 3500 PCM RMS maps to 100%.
    // Real acoustic dB measurements require later calibration.
    const float rms = sqrtf((float)energy / (float)count);
    const int raw = (int)(rms * (100.0f / 3500.0f));
    MicLevelSnapshot sample;
    sample.ready = true;
    sample.levelPercent = (uint8_t)constrain(raw, 0, 100);
    sample.lastSampleMs = millis();

    // Copy PCM into a PSRAM buffer only while the PTT button is still held.
    // A release between readBytes() and this point cannot retain more audio.
    const uint32_t nowMs = millis();
    const bool heldNow = micPttHeld.load(std::memory_order_acquire);
    if (pttAudio != nullptr) {
      const uint32_t freePsram = ESP.getFreePsram();
      if (freePsram < pttPsramMinBytes) pttPsramMinBytes = freePsram;
      const uint32_t age = (uint32_t)(nowMs - pttStartedMs);
      if (!heldNow || age >= MIC_PTT_MAX_MS ||
          pttSamples >= MIC_PTT_MAX_SAMPLES) {
        pttDurationMs = min(age, MIC_PTT_MAX_MS);
        pttLastSamples = (uint32_t)pttSamples;
        const bool expired = age >= MIC_PTT_MAX_MS ||
                             pttSamples >= MIC_PTT_MAX_SAMPLES;
        micPttDiscard(pttAudio, pttSamples);
        pttPsramAfterBytes = ESP.getFreePsram();
        pttSamples = 0;
        pttPhase = expired ? MicPttPhase::TIMEOUT : MicPttPhase::DISCARDED;
        pttArmed = !heldNow;
      } else {
        const size_t left = MIC_PTT_MAX_SAMPLES - pttSamples;
        const size_t take = min(count, left);
        memcpy(pttAudio + pttSamples, pcm, take * sizeof(int16_t));
        micMetricsAccumulate(pttMetrics, pcm, take); // only stored samples
        pttSamples += take;
        pttDurationMs = age;
        pttLastSamples = (uint32_t)pttSamples;
        if (pttSamples == MIC_PTT_MAX_SAMPLES) {
          micPttDiscard(pttAudio, pttSamples);
          pttPsramAfterBytes = ESP.getFreePsram();
          pttSamples = 0;
          pttPhase = MicPttPhase::TIMEOUT;
          pttArmed = false;
          pttDurationMs = MIC_PTT_MAX_MS;
        }
      }
    }
    sample.pttPhase = pttPhase;
    sample.pttDurationMs = pttDurationMs;
    sample.pttSamples = pttLastSamples;
    sample.pttRms = micMetricsRms(pttMetrics);
    sample.pttPeak = pttMetrics.peak;
    sample.pttClipPct = micMetricsClippedPercent(pttMetrics);
    sample.pttRateHz = micMetricsThroughput(pttLastSamples, pttDurationMs);
    sample.pttCoveragePct = micMetricsCoverage(
        pttLastSamples, pttDurationMs, MIC_SAMPLE_RATE);
    sample.pttMemoryValid = pttMemoryValid;
    sample.pttPsramBeforeKB = pttPsramBeforeBytes / 1024;
    sample.pttPsramMinKB = pttPsramMinBytes / 1024;
    sample.pttPsramAfterKB = pttPsramAfterBytes / 1024;
    micLevelPublish(sample);
    // No PCM from the current window remains in this stack buffer.
    memset(pcm, 0, sizeof(pcm));
    // During a hold, keep draining DMA nearly continuously; the old 40ms
    // VU idle delay would otherwise skip most of a voice test.
    vTaskDelay(pdMS_TO_TICKS(pttAudio != nullptr ? 1 : 40));
  }
}

static bool micLevelStart() {
  micLevelMutex = xSemaphoreCreateMutex();
  if (micLevelMutex == nullptr) return false;
  TaskHandle_t handle = nullptr;
  const BaseType_t result = xTaskCreate(
      micLevelTask, "mic-vu", 4096, nullptr, 1, &handle);
  if (result != pdPASS) {
    MicLevelSnapshot failed;
    failed.failed = true;
    micLevelPublish(failed);
    return false;
  }
  return true;
}
