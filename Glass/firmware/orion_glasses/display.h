// ST7789 240x240 LCD Display Driver
#ifndef DISPLAY_H
#define DISPLAY_H

#include <TFT_eSPI.h>
#include <TJpg_Decoder.h>

// TFT_eSPI 설정은 User_Setup.h에서 해야 함
// 또는 platformio.ini에서 정의:
//   -D ST7789_DRIVER
//   -D TFT_WIDTH=240
//   -D TFT_HEIGHT=240
//   -D TFT_MOSI=13
//   -D TFT_SCLK=14
//   -D TFT_CS=15
//   -D TFT_DC=12
//   -D TFT_RST=4
//   -D TFT_BL=2

TFT_eSPI tft = TFT_eSPI();

// JPEG 디코딩 콜백 (TJpg_Decoder용)
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
    if (y >= tft.height()) return false;
    tft.pushImage(x, y, w, h, bitmap);
    return true;
}

void initDisplay() {
    tft.init();
    tft.setRotation(0);
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_CYAN, TFT_BLACK);

    // JPEG 디코더 설정
    TJpgDec.setJpgScale(1);
    TJpgDec.setCallback(tft_output);

    // 백라이트
    pinMode(2, OUTPUT);
    analogWrite(2, 200);  // 밝기 (0-255)

    Serial.println("Display initialized OK");
}

void showBootScreen(const char* msg) {
    tft.fillScreen(TFT_BLACK);

    // ORION 텍스트
    tft.setTextSize(3);
    tft.setTextColor(TFT_CYAN);
    tft.setCursor(50, 90);
    tft.println("ORION");

    // O1 텍스트
    tft.setTextSize(2);
    tft.setCursor(95, 125);
    tft.println("O1");

    // 상태 메시지
    tft.setTextSize(1);
    tft.setTextColor(0x07E0);  // 초록색
    tft.setCursor(40, 180);
    tft.println(msg);
}

void displayHUDFrame(uint8_t* jpegData, size_t len) {
    // JPEG 데이터를 LCD에 직접 디코딩해서 출력
    TJpgDec.drawJpg(0, 0, jpegData, len);
}

void displayPartialUpdate(uint8_t* data, size_t len) {
    // 부분 업데이트: x(2) + y(2) + w(2) + h(2) + JPEG data
    if (len < 8) return;

    uint16_t x = (data[0] << 8) | data[1];
    uint16_t y = (data[2] << 8) | data[3];
    // w, h는 JPEG에서 자동 결정됨
    TJpgDec.drawJpg(x, y, data + 8, len - 8);
}

void setBrightness(uint8_t level) {
    analogWrite(2, level);
}

#endif
