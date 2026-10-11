#pragma once
// OpenNextion ONX3248G035 / CST826 touch mapping for 480x320 Landscape.
// T1 is the user-selected hardware profile from USB raw-coordinate testing.
// T0 remains available only in the opt-in, local USB diagnostic selector.
// Pure math: no Arduino, LVGL, network or filesystem.
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
  // Confirmed T1: portrait CST826 (x,y) -> landscape (y, width-1-x).
  return {
      static_cast<int16_t>(py),
      static_cast<int16_t>(nativeWidth - 1 - px)};
}

// The CST826 may expose native portrait coordinates OR pre-rotated values.
// These eight profiles cover both coordinate-axis orders and both polarities.
// T1 is the permanent production mapping. Diagnostic profiles are volatile.
//   0 native portrait: (479-y, x)   [previous incorrect production mapping]
//   1 native portrait: (y, 319-x)   [selected production mapping]
//   2 landscape raw:  (x, y)       [already corrected by controller]
//   3 landscape raw:  (479-x, y)
//   4 landscape raw:  (x, 319-y)
//   5 landscape raw:  (479-x, 319-y)
//   6 portrait raw:   (y, x)       [axis swap]
//   7 portrait raw:   (479-y,319-x)
static inline LandscapeTouchPoint mapTouchWithProfile(
    int rawX, int rawY, uint8_t profile,
    int nativeWidth = 320, int nativeHeight = 480) {
  const int outWidth = nativeHeight;
  const int outHeight = nativeWidth;
  if (profile == 1) {
    return mapNativeTouchToLandscape(rawX, rawY, nativeWidth, nativeHeight);
  }
  if (profile == 0 || profile == 6 || profile == 7) {
    const int x = landscapeClamp(rawX, nativeWidth);
    const int y = landscapeClamp(rawY, nativeHeight);
    if (profile == 0) return {
        static_cast<int16_t>(outWidth - 1 - y),
        static_cast<int16_t>(x)};
    if (profile == 6) return {
        static_cast<int16_t>(y), static_cast<int16_t>(x)};
    return {
        static_cast<int16_t>(outWidth - 1 - y),
        static_cast<int16_t>(outHeight - 1 - x)};
  }
  const int x = landscapeClamp(rawX, outWidth);
  const int y = landscapeClamp(rawY, outHeight);
  switch (profile) {
    case 2: return {static_cast<int16_t>(x), static_cast<int16_t>(y)};
    case 3: return {static_cast<int16_t>(outWidth - 1 - x),
                    static_cast<int16_t>(y)};
    case 4: return {static_cast<int16_t>(x),
                    static_cast<int16_t>(outHeight - 1 - y)};
    case 5: return {static_cast<int16_t>(outWidth - 1 - x),
                    static_cast<int16_t>(outHeight - 1 - y)};
    default: return mapNativeTouchToLandscape(rawX, rawY,
                                              nativeWidth, nativeHeight);
  }
}
