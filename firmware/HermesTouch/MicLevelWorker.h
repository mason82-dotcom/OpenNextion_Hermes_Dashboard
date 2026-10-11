#pragma once
// Optional LOCAL-ONLY PDM microphone level meter for ONX3248G035.
// NO PCM retention, recording, filesystem, HTTP, WiFi, Hermes API or LVGL.
// Only a scaled aggregate amplitude is shared with the GUI via a mutex.
// Hardware: MIC_PDM CLK GPIO19, DATA GPIO20, Arduino-ESP32 core 3.3.2 ESP_I2S.
#include <Arduino.h>
#include <ESP_I2S.h>
#include <math.h>
#include "BoardConfig.h"

static constexpr uint32_t MIC_SAMPLE_RATE = 16000;
static constexpr size_t MIC_PCM_SAMPLES = 256;
static constexpr uint32_t MIC_SAMPLE_TIMEOUT_MS = 150;
static constexpr uint32_t MIC_VALID_AGE_MS = 1500;

struct MicLevelSnapshot {
  bool ready = false;
  bool failed = false;
  uint8_t levelPercent = 0; // relative amplitude, not calibrated sound pressure
  uint32_t lastSampleMs = 0;
};

static SemaphoreHandle_t micLevelMutex = nullptr;
static MicLevelSnapshot micLevelShared;
static I2SClass micLevelI2S;

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
    micLevelPublish(failed);
    micLevelI2S.end();
    vTaskDelete(nullptr);
    return;
  }
  micLevelI2S.setTimeout(MIC_SAMPLE_TIMEOUT_MS);

  int16_t pcm[MIC_PCM_SAMPLES];
  uint8_t failedReads = 0;
  for (;;) {
    // ESP_I2S readBytes() runs ONLY inside this separate FreeRTOS task.
    // PCM exists solely in this stack buffer and is discarded every cycle.
    const size_t got = micLevelI2S.readBytes(
        reinterpret_cast<char *>(pcm), sizeof(pcm));
    if (got < sizeof(int16_t) * 32 || (got % sizeof(int16_t)) != 0) {
      if (++failedReads >= 3) {
        MicLevelSnapshot failed;
        failed.failed = true;
        micLevelPublish(failed);
      }
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
    micLevelPublish(sample);
    vTaskDelay(pdMS_TO_TICKS(40));
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
