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
