#pragma once
// Pure, host-testable diagnostic math for a single LOCAL push-to-talk trial.
// No PCM is retained: only energy, peak, clipping count, and sample count.
// No ESP, WiFi, LVGL, Hermes, filesystem, or transport dependency.
#include <cstddef>
#include <cstdint>
#include <cmath>

static constexpr uint32_t MIC_DIAG_CLIP_THRESHOLD = 32000;

struct MicAudioMetrics {
  uint64_t energy = 0;
  uint32_t samples = 0;
  uint16_t peak = 0;
  uint32_t clipped = 0;
};

// 'count' is the number of samples *actually copied into* the PTT buffer.
// The input pointer is never stored.
static inline void micMetricsAccumulate(
    MicAudioMetrics &total, const int16_t *pcm, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    const int32_t value = (int32_t)pcm[i];
    const uint32_t magnitude = (uint32_t)(value < 0 ? -value : value);
    total.energy += (uint64_t)(value * value);
    if (magnitude > total.peak) total.peak = (uint16_t)magnitude;
    if (magnitude >= MIC_DIAG_CLIP_THRESHOLD) ++total.clipped;
  }
  total.samples += (uint32_t)count;
}

static inline uint16_t micMetricsRms(const MicAudioMetrics &m) {
  if (m.samples == 0) return 0;
  const float rms = sqrtf((float)m.energy / (float)m.samples);
  return (uint16_t)(rms > 32768.0f ? 32768 : rms + 0.5f);
}

static inline uint8_t micMetricsClippedPercent(const MicAudioMetrics &m) {
  if (m.samples == 0) return 0;
  return (uint8_t)((uint64_t)m.clipped * 100u / m.samples);
}

// Diagnostic PCM throughput, NOT proof of an exact or gapless I2S clock.
// Returns 0 for captures shorter than 200ms, where rate is unstable.
static inline uint32_t micMetricsThroughput(
    uint32_t samples, uint32_t elapsedMs) {
  if (elapsedMs < 200) return 0;
  return (uint32_t)((uint64_t)samples * 1000u / elapsedMs);
}

static inline uint8_t micMetricsCoverage(
    uint32_t samples, uint32_t elapsedMs, uint32_t targetRateHz) {
  if (elapsedMs < 200 || targetRateHz == 0) return 0;
  const uint64_t expected = (uint64_t)targetRateHz * elapsedMs;
  uint64_t percent = (uint64_t)samples * 100000u / expected;
  if (percent > 100) percent = 100;
  return (uint8_t)percent;
}
