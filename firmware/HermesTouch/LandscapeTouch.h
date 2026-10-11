#pragma once
// Pure 90-degree clockwise touch mapping. CST826 reports portrait/raw axes.
// Tested mathematically on host; actual glass orientation needs board check.
#include <cstdint>

struct LandscapeTouchPoint {
  int16_t x;
  int16_t y;
};

static inline int landscapeClamp(int value, int maxExclusive) {
  if (value < 0) return 0;
  if (value >= maxExclusive) return maxExclusive - 1;
  return value;
}

static inline LandscapeTouchPoint mapNativeTouchToLandscape(
    int rawX, int rawY, int nativeWidth = 320, int nativeHeight = 480) {
  const int px = landscapeClamp(rawX, nativeWidth);
  const int py = landscapeClamp(rawY, nativeHeight);
  return {
      static_cast<int16_t>(nativeHeight - 1 - py),
      static_cast<int16_t>(px)};
}
