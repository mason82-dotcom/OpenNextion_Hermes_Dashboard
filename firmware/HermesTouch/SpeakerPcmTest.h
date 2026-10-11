#pragma once
// Host-testable, bounded PCM synthesis for the explicitly LOCAL speaker test.
// There is no file, transport, text-to-speech, or microphone input.
// The fixed waveform is created on demand in the speaker task's scratch buffer.
#include <cstddef>
#include <cstdint>
#include <cmath>

static constexpr uint32_t SPK_TEST_SAMPLE_RATE = 16000;
static constexpr uint32_t SPK_TEST_TONE_HZ = 660;
static constexpr uint32_t SPK_TEST_DURATION_MS = 250;
static constexpr uint16_t SPK_TEST_MAX_AMPLITUDE = 2500;
static constexpr size_t SPK_TEST_TOTAL_SAMPLES =
    SPK_TEST_SAMPLE_RATE * SPK_TEST_DURATION_MS / 1000;
static constexpr size_t SPK_TEST_FADE_SAMPLES = SPK_TEST_SAMPLE_RATE / 100;
static_assert(SPK_TEST_TOTAL_SAMPLES == 4000,
              "Local tone must remain bounded to 250ms/4000 samples");

// User volume is a percent of the *previously hardware-tested* quiet tone.
// The cap never increases output beyond the v0.8.3 level. No dB claim.
static inline uint8_t speakerClampLevel(int percent) {
  if (percent < 0) return 0;
  if (percent > 100) return 100;
  return static_cast<uint8_t>(percent);
}

static inline uint16_t speakerLevelAmplitude(int percent) {
  return static_cast<uint16_t>(
      (static_cast<uint32_t>(SPK_TEST_MAX_AMPLITUDE) *
       speakerClampLevel(percent)) / 100u);
}

// Render only the remaining portion of a fixed, bounded mono PCM test signal.
// The caller owns the buffer; this function does not retain its address.
// Return the count of generated samples, never more than destCapacity.
static inline size_t speakerRenderLocalTestTone(
    int16_t *dest, size_t destCapacity, size_t firstFrame, int levelPercent) {
  if (dest == nullptr || destCapacity == 0 ||
      firstFrame >= SPK_TEST_TOTAL_SAMPLES) return 0;
  const size_t remaining = SPK_TEST_TOTAL_SAMPLES - firstFrame;
  const size_t take = destCapacity < remaining ? destCapacity : remaining;
  const float amplitude = static_cast<float>(
      speakerLevelAmplitude(levelPercent));
  for (size_t i = 0; i < take; ++i) {
    const size_t n = firstFrame + i;
    const size_t framesLeft = SPK_TEST_TOTAL_SAMPLES - 1 - n;
    size_t fade = n < framesLeft ? n : framesLeft;
    if (fade > SPK_TEST_FADE_SAMPLES) fade = SPK_TEST_FADE_SAMPLES;
    const float gain = static_cast<float>(fade) /
                       static_cast<float>(SPK_TEST_FADE_SAMPLES);
    const float angle = 6.283185307f * static_cast<float>(SPK_TEST_TONE_HZ) *
                        static_cast<float>(n) /
                        static_cast<float>(SPK_TEST_SAMPLE_RATE);
    dest[i] = static_cast<int16_t>(amplitude * gain * sinf(angle));
  }
  return take;
}
