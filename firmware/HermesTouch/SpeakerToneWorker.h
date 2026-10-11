#pragma once
// Strictly LOCAL test tone for the ONX3248G035 / NS4168 speaker.
// Audio only: NO network, recording, Hermes, LVGL, filesystem or mic changes.
// PDM RX keeps Arduino ESP_I2S (I2S0); speaker uses manufacturer's I2S1 TX.
#include <Arduino.h>
#include <driver/i2s_std.h>
#include <atomic>
#include <cstring>
#include <math.h>
#include "BoardConfig.h"

static constexpr uint32_t SPK_SAMPLE_RATE = 16000;
static constexpr uint32_t SPK_TONE_HZ = 660;
static constexpr uint32_t SPK_TONE_MS = 250;
static constexpr uint32_t SPK_AMPLITUDE = 2500; // <8% of signed 16-bit FS
static constexpr size_t SPK_CHUNK_SAMPLES = 256;
static constexpr uint32_t SPK_AMP_WAIT_MS = 250;
static constexpr uint32_t SPK_PLAY_DEADLINE_MS = 700;

enum class SpeakerTonePhase : uint8_t {
  STARTING, READY, QUEUED, WAIT_AMP, PLAYING, WAIT_MUTE, DONE, ERROR
};

struct SpeakerToneSnapshot {
  SpeakerTonePhase phase = SpeakerTonePhase::STARTING;
  uint32_t completed = 0;
};

static SemaphoreHandle_t speakerToneMutex = nullptr;
static SpeakerToneSnapshot speakerToneShared;
static std::atomic<bool> speakerTonePending{false};
static std::atomic<bool> speakerToneAmpAck{false};

// Only the main/LVGL task can request a tone.
static bool speakerToneRequest() {
  if (speakerToneMutex == nullptr) return false;
  if (xSemaphoreTake(speakerToneMutex, 0) != pdTRUE) return false;
  const SpeakerTonePhase phase = speakerToneShared.phase;
  if (phase != SpeakerTonePhase::READY && phase != SpeakerTonePhase::DONE) {
    xSemaphoreGive(speakerToneMutex);
    return false;
  }
  // Reserve the state under the same mutex before signalling the worker,
  // so rapid double taps cannot queue a second tone while the first plays.
  speakerToneShared.phase = SpeakerTonePhase::QUEUED;
  speakerTonePending.store(true, std::memory_order_release);
  xSemaphoreGive(speakerToneMutex);
  return true;
}

static void speakerToneAmpAcknowledged(bool enabled) {
  speakerToneAmpAck.store(enabled, std::memory_order_release);
}

static bool speakerToneRead(SpeakerToneSnapshot &out) {
  if (speakerToneMutex == nullptr ||
      xSemaphoreTake(speakerToneMutex, 0) != pdTRUE) return false;
  out = speakerToneShared;
  xSemaphoreGive(speakerToneMutex);
  return true;
}

static void speakerTonePublish(SpeakerTonePhase phase, uint32_t completed) {
  if (speakerToneMutex != nullptr &&
      xSemaphoreTake(speakerToneMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
    speakerToneShared.phase = phase;
    speakerToneShared.completed = completed;
    xSemaphoreGive(speakerToneMutex);
  }
}

static void speakerToneTask(void *) {
  // Separate hardware I2S peripheral: official OpenNextion Arduino example
  // assigns PDM input to I2S0 and NS4168 output to I2S1.
  i2s_chan_handle_t speakerTx = nullptr;
  i2s_chan_config_t chanCfg =
      I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
  chanCfg.dma_desc_num = 4;
  chanCfg.dma_frame_num = SPK_CHUNK_SAMPLES;

  bool ok = i2s_new_channel(&chanCfg, &speakerTx, nullptr) == ESP_OK;
  if (ok) {
    i2s_std_config_t txCfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SPK_SAMPLE_RATE),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = (gpio_num_t)SPEAKER_BCLK_PIN,
            .ws = (gpio_num_t)SPEAKER_WS_PIN,
            .dout = (gpio_num_t)SPEAKER_DATA_PIN,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    ok = i2s_channel_init_std_mode(speakerTx, &txCfg) == ESP_OK;
  }
  if (ok) ok = i2s_channel_enable(speakerTx) == ESP_OK;
  if (!ok) {
    speakerTonePublish(SpeakerTonePhase::ERROR, 0);
    if (speakerTx != nullptr) i2s_del_channel(speakerTx);
    vTaskDelete(nullptr);
    return;
  }

  speakerTonePublish(SpeakerTonePhase::READY, 0);
  uint32_t completed = 0;
  int16_t pcm[SPK_CHUNK_SAMPLES];
  for (;;) {
    if (!speakerTonePending.exchange(false, std::memory_order_acq_rel)) {
      vTaskDelay(pdMS_TO_TICKS(15));
      continue;
    }
    // The PCF8574 expander is owned by the MAIN task exclusively. Worker
    // waits for main to enable the amplifier; no Wire calls from this task.
    speakerToneAmpAck.store(false, std::memory_order_release);
    speakerTonePublish(SpeakerTonePhase::WAIT_AMP, completed);
    uint32_t started = millis();
    while (!speakerToneAmpAck.load(std::memory_order_acquire) &&
           (uint32_t)(millis() - started) < SPK_AMP_WAIT_MS) {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
    if (!speakerToneAmpAck.load(std::memory_order_acquire)) {
      speakerTonePublish(SpeakerTonePhase::ERROR, completed);
      continue;
    }

    speakerTonePublish(SpeakerTonePhase::PLAYING, completed);
    const uint32_t totalSamples = SPK_SAMPLE_RATE * SPK_TONE_MS / 1000;
    const uint32_t fadeSamples = SPK_SAMPLE_RATE / 100; // 10ms fade
    const uint32_t playbackStartMs = millis();
    uint32_t frame = 0;
    bool writeOk = true;
    while (frame < totalSamples) {
      if ((uint32_t)(millis() - playbackStartMs) >= SPK_PLAY_DEADLINE_MS) {
        writeOk = false;
        break;
      }
      const size_t count = min((size_t)(totalSamples - frame),
                               SPK_CHUNK_SAMPLES);
      for (size_t i = 0; i < count; ++i) {
        const uint32_t n = frame + i;
        const uint32_t left = totalSamples - 1 - n;
        const uint32_t envelope = min(min(n, left), fadeSamples);
        const float gain = (float)envelope / (float)fadeSamples;
        const float angle = 6.2831853f * (float)SPK_TONE_HZ *
                            (float)n / (float)SPK_SAMPLE_RATE;
        pcm[i] = (int16_t)(SPK_AMPLITUDE * gain * sinf(angle));
      }
      size_t bytesWritten = 0;
      const size_t required = count * sizeof(int16_t);
      if (i2s_channel_write(speakerTx, pcm, required, &bytesWritten, 100) !=
              ESP_OK || bytesWritten != required) {
        writeOk = false;
        break;
      }
      frame += (uint32_t)count;
    }
    memset(pcm, 0, sizeof(pcm));
    // Ask GUI/main task to mute. Do not start a second tone while amplifying.
    speakerTonePublish(SpeakerTonePhase::WAIT_MUTE, completed);
    uint32_t muteStart = millis();
    while (speakerToneAmpAck.load(std::memory_order_acquire) &&
           (uint32_t)(millis() - muteStart) < SPK_AMP_WAIT_MS) {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
    if (speakerToneAmpAck.load(std::memory_order_acquire)) {
      speakerTonePublish(SpeakerTonePhase::ERROR, completed);
    } else if (writeOk) {
      ++completed;
      speakerTonePublish(SpeakerTonePhase::DONE, completed);
    } else {
      speakerTonePublish(SpeakerTonePhase::ERROR, completed);
    }
  }
}

static bool speakerToneStart() {
  speakerToneMutex = xSemaphoreCreateMutex();
  if (speakerToneMutex == nullptr) return false;
  speakerTonePublish(SpeakerTonePhase::STARTING, 0);
  TaskHandle_t handle = nullptr;
  const BaseType_t result = xTaskCreate(
      speakerToneTask, "spk-tone", 4096, nullptr, 1, &handle);
  if (result != pdPASS) {
    speakerTonePublish(SpeakerTonePhase::ERROR, 0);
    return false;
  }
  return true;
}
