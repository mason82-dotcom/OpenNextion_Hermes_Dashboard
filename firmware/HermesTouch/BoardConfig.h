#pragma once
#include <Arduino.h>
// OpenNextion ONX3248G035: official 09_outofbox_demo mapping.
static constexpr uint8_t NEXTION_IIC_SCL_PIN = 7;
static constexpr uint8_t NEXTION_IIC_SDA_PIN = 8;
static constexpr uint16_t LCD_H_RES = 320;
static constexpr uint16_t LCD_V_RES = 480;
static constexpr int8_t LCD_SCLK_PIN = 5;
static constexpr int8_t LCD_MOSI_PIN = 1;
static constexpr int8_t LCD_MISO_PIN = -1;
static constexpr uint8_t LCD_DC_PIN = 3;
static constexpr uint8_t LCD_CS_PIN = 2;
static constexpr uint8_t LCD_BL_PIN = 6;
// Official MIC_PDM connector (shared with GPIO expansion; no camera used).
static constexpr int8_t MIC_PDM_CLK_PIN = 19;
static constexpr int8_t MIC_PDM_DATA_PIN = 20;
static constexpr uint8_t CST826_ADDR = 0x15;
static constexpr uint8_t PCF8574_ADDR = 0x38;
static constexpr uint8_t PCF8574_PIN_LCD_RST = 6;
// Official OpenNextion Arduino 07_microphone_test: NS4168 I2S speaker.
// Audio output is *separately opt-in*; PCF8574 P0 controls amplifier enable.
static constexpr uint8_t PCF8574_PIN_I2S_CTRL = 0;
static constexpr int8_t SPEAKER_BCLK_PIN = 14;
static constexpr int8_t SPEAKER_DATA_PIN = 15;
static constexpr int8_t SPEAKER_WS_PIN = 16;
