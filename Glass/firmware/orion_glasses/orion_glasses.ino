/*
 * ===================================================
 *  ORION O1 - EDITH Smart Glasses Firmware
 *  ESP32-S3 + OV2640 Camera + ST7789 LCD
 * ===================================================
 *
 *  기능:
 *  - OV2640 카메라로 JPEG 캡처 → WiFi → 맥북 서버 전송
 *  - 서버에서 HUD 프레임(JPEG) 수신 → ST7789 LCD에 표시
 *  - 배터리 모니터링 → 서버에 전송
 *
 *  라이브러리 필요:
 *  - WebSockets by Markus Sattler
 *  - TFT_eSPI by Bodmer
 *  - TJpg_Decoder by Bodmer
 *  - ArduinoJson by Benoit Blanchon
 *
 *  보드: ESP32-S3 Dev Module
 * ===================================================
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "wifi_config.h"
#include "camera.h"
#include "display.h"

// --- 설정 ---
#define CAMERA_FPS        5        // 카메라 프레임 전송 속도
#define STATUS_INTERVAL   10000    // 상태 전송 간격 (ms)
#define BATTERY_PIN       33       // 배터리 ADC 핀
#define BUTTON_PIN        0        // 부팅 버튼 (GPIO0)

// --- 전역 변수 ---
WebSocketsClient ws;
bool wsConnected = false;
unsigned long lastCapture = 0;
unsigned long lastStatus = 0;
unsigned long buttonPressTime = 0;
bool buttonPressed = false;

// --- 배터리 전압 읽기 ---
int getBatteryPercent() {
    int raw = analogRead(BATTERY_PIN);
    float voltage = (raw / 4095.0) * 3.3 * 2;  // 분압 회로 가정
    // 3.0V = 0%, 4.2V = 100%
    int percent = (int)((voltage - 3.0) / 1.2 * 100);
    return constrain(percent, 0, 100);
}

// --- WebSocket 이벤트 핸들러 ---
void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            wsConnected = false;
            Serial.println("[WS] Disconnected");
            showBootScreen("Reconnecting...");
            break;

        case WStype_CONNECTED:
            wsConnected = true;
            Serial.println("[WS] Connected!");
            showBootScreen("ONLINE");
            delay(500);

            // 디바이스 정보 전송
            {
                StaticJsonDocument<128> doc;
                doc["device"] = "orion_glasses";
                doc["version"] = "1.0";
                doc["battery"] = getBatteryPercent();
                String json;
                serializeJson(doc, json);
                ws.sendTXT(json);
            }
            break;

        case WStype_BIN:
            if (length > 0) {
                uint8_t msgType = payload[0];

                if (msgType == 0x02) {
                    // 전체 HUD 프레임 (JPEG)
                    displayHUDFrame(payload + 1, length - 1);
                }
                else if (msgType == 0x03) {
                    // 부분 HUD 업데이트
                    displayPartialUpdate(payload + 1, length - 1);
                }
                else if (msgType == 0x06) {
                    // 명령 (JSON)
                    StaticJsonDocument<128> doc;
                    DeserializationError err = deserializeJson(doc, payload + 1, length - 1);
                    if (!err) {
                        const char* action = doc["action"];
                        if (strcmp(action, "sleep") == 0) {
                            Serial.println("[CMD] Sleep");
                            setBrightness(0);
                            esp_deep_sleep_start();
                        }
                        else if (strcmp(action, "brightness") == 0) {
                            int val = doc["value"];
                            setBrightness(val);
                        }
                    }
                }
            }
            break;

        case WStype_TEXT:
            // JSON 텍스트 메시지
            Serial.printf("[WS] Text: %s\n", payload);
            break;

        default:
            break;
    }
}

// --- 카메라 프레임 전송 ---
void sendCameraFrame() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Camera capture failed");
        return;
    }

    if (wsConnected) {
        // 0x01 헤더 + JPEG 데이터
        uint8_t header = 0x01;

        // WebSocket 바이너리 메시지로 전송
        // 헤더와 데이터를 합쳐서 전송
        size_t totalLen = 1 + fb->len;
        uint8_t* buf = (uint8_t*)malloc(totalLen);
        if (buf) {
            buf[0] = header;
            memcpy(buf + 1, fb->buf, fb->len);
            ws.sendBIN(buf, totalLen);
            free(buf);
        }
    }

    esp_camera_fb_return(fb);
}

// --- 상태 전송 ---
void sendStatus() {
    if (!wsConnected) return;

    StaticJsonDocument<128> doc;
    doc["battery"] = getBatteryPercent();
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["fps"] = CAMERA_FPS;
    doc["uptime"] = millis() / 1000;

    String json;
    serializeJson(doc, json);

    size_t totalLen = 1 + json.length();
    uint8_t* buf = (uint8_t*)malloc(totalLen);
    if (buf) {
        buf[0] = 0x04;  // 상태 메시지 헤더
        memcpy(buf + 1, json.c_str(), json.length());
        ws.sendBIN(buf, totalLen);
        free(buf);
    }
}

// --- 버튼 처리 ---
void handleButton() {
    bool pressed = (digitalRead(BUTTON_PIN) == LOW);

    if (pressed && !buttonPressed) {
        buttonPressTime = millis();
        buttonPressed = true;
    }
    else if (!pressed && buttonPressed) {
        unsigned long duration = millis() - buttonPressTime;
        buttonPressed = false;

        if (wsConnected) {
            uint8_t msg[2];
            msg[0] = 0x05;  // 버튼 메시지 헤더
            msg[1] = (duration > 1000) ? 0x01 : 0x00;  // 롱프레스 vs 숏프레스
            ws.sendBIN(msg, 2);
            Serial.printf("[BTN] %s press\n", (duration > 1000) ? "Long" : "Short");
        }
    }
}

// --- Setup ---
void setup() {
    Serial.begin(115200);
    Serial.println("\n=== ORION O1 Smart Glasses ===");

    // 버튼 설정
    pinMode(BUTTON_PIN, INPUT_PULLUP);

    // 1. 디스플레이 초기화
    initDisplay();
    showBootScreen("Booting...");
    Serial.println("[OK] Display");

    // 2. 카메라 초기화
    if (initCamera()) {
        showBootScreen("Camera OK");
        Serial.println("[OK] Camera");
    } else {
        showBootScreen("Camera FAIL");
        Serial.println("[FAIL] Camera");
    }

    // 3. WiFi 연결
    showBootScreen("WiFi...");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[OK] WiFi: %s\n", WiFi.localIP().toString().c_str());
        showBootScreen("WiFi OK");
    } else {
        Serial.println("\n[FAIL] WiFi");
        showBootScreen("WiFi FAIL");
        return;
    }

    // 4. WebSocket 연결
    showBootScreen("Server...");
    String wsPath = "/ws/glasses";
    ws.begin(SERVER_IP, SERVER_PORT, wsPath.c_str());
    ws.onEvent(webSocketEvent);
    ws.setReconnectInterval(3000);
    Serial.printf("[OK] WebSocket -> %s:%d\n", SERVER_IP, SERVER_PORT);

    showBootScreen("ORION O1 READY");
    delay(1000);
}

// --- Loop ---
void loop() {
    ws.loop();
    handleButton();

    unsigned long now = millis();

    // 카메라 프레임 전송 (5 FPS)
    if (now - lastCapture > (1000 / CAMERA_FPS)) {
        sendCameraFrame();
        lastCapture = now;
    }

    // 상태 전송 (10초마다)
    if (now - lastStatus > STATUS_INTERVAL) {
        sendStatus();
        lastStatus = now;
    }
}
