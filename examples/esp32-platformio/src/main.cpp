/**
 * Agent Presentation Protocol (APP) — ESP-32 Headless Bridge (PlatformIO)
 *
 * Connects an ESP-32 to an APP relay as a headless device.
 * Demonstrates: LED control, button input, temperature sensor (DHT22),
 * Agent Card declaration, sensor event reporting, and device_action handling.
 *
 * DISCLAIMER: This code is provided as-is for reference only. It has not
 * been tested on physical hardware. See the top-level README for details.
 *
 * Hardware (suggested):
 *   - ESP-32 DevKit v1 (or any ESP-32 board with WiFi)
 *   - DHT22 temperature/humidity sensor on GPIO 4
 *   - LED on GPIO 2 (many boards have a built-in LED here)
 *   - Pushbutton on GPIO 15 (pulled up internally)
 *
 * Libraries (installed via platformio.ini):
 *   - ArduinoWebsockets by Gil Maimon
 *   - ArduinoJson by Benoit Blanchon
 *   - DHT sensor library by Adafruit
 */

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <esp_system.h>  // esp_random()

// ============================================================
// CONFIGURATION — Edit these values for your setup
// ============================================================

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BRIDGE_TOKEN  = "YOUR_BRIDGE_TOKEN";
const char* RELAY_HOST    = "your-relay.example";
const int   RELAY_PORT    = 443;
const char* RELAY_PATH    = "/ws/bridge";

// Hardware pins
const int LED_PIN    = 2;
const int BUTTON_PIN = 15;
const int DHT_PIN    = 4;

// Timing
const unsigned long SENSOR_INTERVAL_MS   = 30000;  // Report sensors every 30s
const unsigned long HEARTBEAT_INTERVAL   = 25000;  // Ping every 25s (server expects 30s)
const unsigned long RECONNECT_INITIAL_MS = 1000;
const unsigned long RECONNECT_MAX_MS     = 60000;

// ============================================================
// Global state
// ============================================================

using namespace websockets;
WebsocketsClient wsClient;
DHT dht(DHT_PIN, DHT22);

bool ledState = false;
bool lastButtonState = HIGH;
float lastTemperature = 0.0;
float lastHumidity = 0.0;

unsigned long lastSensorReport = 0;
unsigned long lastHeartbeat = 0;
unsigned long reconnectDelay = RECONNECT_INITIAL_MS;
bool wsConnected = false;

// ============================================================
// JSON helpers
// ============================================================

// 128-bit random hex string formatted UUID-style. ESP-32 has no UUID
// library and the v4 format-specific bits are not enforced — this id is
// a dedup/correlation key, not a security identifier. See README
// "Protocol notes" for context.
String makeId() {
  char buf[37];  // 8+1+4+1+4+1+4+1+12 + null
  uint32_t r1 = esp_random();
  uint32_t r2 = esp_random();
  uint32_t r3 = esp_random();
  uint32_t r4 = esp_random();
  snprintf(buf, sizeof(buf), "%08lx-%04lx-%04lx-%04lx-%04lx%08lx",
           (unsigned long)r1,
           (unsigned long)(r2 >> 16),
           (unsigned long)(r2 & 0xffff),
           (unsigned long)(r3 >> 16),
           (unsigned long)(r3 & 0xffff),
           (unsigned long)r4);
  return String(buf);
}

String buildAgentCard() {
  JsonDocument doc;
  doc["type"] = "agent_card";

  // SPEC §3.3: agent_card wraps the card document under a "card" key.
  JsonObject card = doc["card"].to<JsonObject>();
  card["protocol_version"] = "0.4";

  JsonObject agent = card["agent"].to<JsonObject>();
  agent["name"] = "ESP-32 Sensor Hub";
  agent["version"] = "1.0.0";
  agent["description"] = "ESP-32 headless bridge with LED, button, and DHT22 sensor";

  JsonObject device = card["device"].to<JsonObject>();
  device["type"] = "sensor_hub";
  device["manufacturer"] = "Espressif";
  device["model"] = "ESP-32 DevKit";
  device["interaction_model"] = "headless";

  // Current sensor status
  JsonObject status = device["status"].to<JsonObject>();
  status["led"] = ledState ? "on" : "off";
  status["temperature_c"] = lastTemperature;
  status["humidity_pct"] = lastHumidity;
  status["button"] = digitalRead(BUTTON_PIN) == LOW ? "pressed" : "released";
  status["uptime_ms"] = millis();
  status["wifi_rssi"] = WiFi.RSSI();

  // Available actions (nested under device per SPEC §5.2)
  JsonArray actions = device["available_actions"].to<JsonArray>();

  // Action: set_led
  JsonObject setLed = actions.add<JsonObject>();
  setLed["id"] = "set_led";
  setLed["name"] = "Set LED";
  setLed["description"] = "Turn the onboard LED on or off";
  JsonArray ledParams = setLed["params"].to<JsonArray>();
  JsonObject ledStateParam = ledParams.add<JsonObject>();
  ledStateParam["name"] = "state";
  ledStateParam["type"] = "string";
  ledStateParam["required"] = true;
  JsonArray ledOptions = ledStateParam["options"].to<JsonArray>();
  ledOptions.add("on");
  ledOptions.add("off");
  ledOptions.add("toggle");

  // Action: set_led_brightness (PWM)
  JsonObject brightness = actions.add<JsonObject>();
  brightness["id"] = "set_led_brightness";
  brightness["name"] = "Set LED Brightness";
  brightness["description"] = "Set the LED brightness level (0-255)";
  JsonArray brightParams = brightness["params"].to<JsonArray>();
  JsonObject brightLevel = brightParams.add<JsonObject>();
  brightLevel["name"] = "level";
  brightLevel["type"] = "integer";
  brightLevel["required"] = true;
  brightLevel["min"] = 0;
  brightLevel["max"] = 255;

  // Action: read_sensors
  JsonObject readSensors = actions.add<JsonObject>();
  readSensors["id"] = "read_sensors";
  readSensors["name"] = "Read Sensors";
  readSensors["description"] = "Take an immediate sensor reading and report current temperature, humidity, and button state";

  // Action: blink_led
  JsonObject blink = actions.add<JsonObject>();
  blink["id"] = "blink_led";
  blink["name"] = "Blink LED";
  blink["description"] = "Blink the LED a specified number of times";
  JsonArray blinkParams = blink["params"].to<JsonArray>();
  JsonObject blinkCount = blinkParams.add<JsonObject>();
  blinkCount["name"] = "count";
  blinkCount["type"] = "integer";
  blinkCount["required"] = false;
  blinkCount["min"] = 1;
  blinkCount["max"] = 20;

  // Capabilities. Headless device: interaction_model="headless" plus
  // omitted input_accepts/output_modalities declares no direct human I/O.
  JsonObject caps = card["capabilities"].to<JsonObject>();
  caps["streaming"] = false;
  caps["emotions"].to<JsonArray>();  // empty array — no emotion support

  String output;
  serializeJson(doc, output);
  return output;
}

String buildSensorEvent(const char* trigger = "periodic") {
  JsonDocument doc;
  doc["type"] = "sensor_event";
  doc["id"] = makeId();
  doc["sensor"] = "environment";

  JsonObject value = doc["value"].to<JsonObject>();
  value["temperature_c"] = lastTemperature;
  value["humidity_pct"] = lastHumidity;
  value["led"] = ledState ? "on" : "off";
  value["button"] = digitalRead(BUTTON_PIN) == LOW ? "pressed" : "released";
  value["uptime_ms"] = millis();
  value["wifi_rssi"] = WiFi.RSSI();
  value["free_heap"] = ESP.getFreeHeap();

  doc["trigger"] = trigger;
  // ESP-32 DevKit has no real-time clock by default; timestamp is
  // monotonic ms-since-boot. See README "Protocol notes". Downstream
  // consumers needing wall-clock time should stamp it on receipt.
  doc["timestamp"] = millis();

  String output;
  serializeJson(doc, output);
  return output;
}

// ============================================================
// Action handlers
// ============================================================

void handleSetLed(JsonObject& params) {
  String state = params["state"] | "toggle";
  if (state == "on") {
    ledState = true;
  } else if (state == "off") {
    ledState = false;
  } else if (state == "toggle") {
    ledState = !ledState;
  }
  digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  Serial.printf("[ACTION] LED set to %s\n", ledState ? "ON" : "OFF");
}

void handleSetBrightness(JsonObject& params) {
  int level = params["level"] | 0;
  level = constrain(level, 0, 255);
  analogWrite(LED_PIN, level);
  ledState = (level > 0);
  Serial.printf("[ACTION] LED brightness set to %d\n", level);
}

void handleBlinkLed(JsonObject& params) {
  int count = params["count"] | 3;
  count = constrain(count, 1, 20);
  Serial.printf("[ACTION] Blinking LED %d times\n", count);
  for (int i = 0; i < count; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(200);
    digitalWrite(LED_PIN, LOW);
    delay(200);
  }
  // Restore previous state
  digitalWrite(LED_PIN, ledState ? HIGH : LOW);
}

void handleReadSensors() {
  lastTemperature = dht.readTemperature();
  lastHumidity = dht.readHumidity();
  if (isnan(lastTemperature)) lastTemperature = 0.0;
  if (isnan(lastHumidity)) lastHumidity = 0.0;
  Serial.printf("[ACTION] Sensor read: %.1f°C, %.1f%%\n", lastTemperature, lastHumidity);

  // Send immediate sensor event
  if (wsConnected) {
    wsClient.send(buildSensorEvent());
  }
}

// ============================================================
// WebSocket handlers
// ============================================================

void onMessage(WebsocketsMessage message) {
  Serial.printf("[WS] Received: %s\n", message.data().c_str());

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, message.data());
  if (err) {
    Serial.printf("[WS] JSON parse error: %s\n", err.c_str());
    return;
  }

  const char* type = doc["type"];
  if (!type) return;

  if (strcmp(type, "device_action") == 0) {
    const char* action = doc["action"];
    JsonObject params = doc["parameters"].as<JsonObject>();

    Serial.printf("[ACTION] Received: %s\n", action);

    if (strcmp(action, "set_led") == 0) {
      handleSetLed(params);
    } else if (strcmp(action, "set_led_brightness") == 0) {
      handleSetBrightness(params);
    } else if (strcmp(action, "blink_led") == 0) {
      handleBlinkLed(params);
    } else if (strcmp(action, "read_sensors") == 0) {
      handleReadSensors();
    } else {
      Serial.printf("[ACTION] Unknown action: %s\n", action);
      // Send error back
      JsonDocument errDoc;
      errDoc["type"] = "error";
      errDoc["code"] = "unknown_action";
      errDoc["message"] = String("Unknown action: ") + action;
      String errStr;
      serializeJson(errDoc, errStr);
      wsClient.send(errStr);
    }

    // Report updated state after any action
    if (wsConnected) {
      wsClient.send(buildSensorEvent("event"));
    }
  }
}

void onEvent(WebsocketsEvent event, String data) {
  switch (event) {
    case WebsocketsEvent::ConnectionOpened:
      Serial.println("[WS] Connected to relay");
      wsConnected = true;
      reconnectDelay = RECONNECT_INITIAL_MS;

      // Send Agent Card immediately on connect
      wsClient.send(buildAgentCard());
      Serial.println("[WS] Agent Card sent");

      // Send initial sensor reading
      handleReadSensors();
      break;

    case WebsocketsEvent::ConnectionClosed:
      Serial.println("[WS] Disconnected from relay");
      wsConnected = false;
      break;

    case WebsocketsEvent::GotPing:
      Serial.println("[WS] Ping received");
      break;

    case WebsocketsEvent::GotPong:
      break;
  }
}

// ============================================================
// WiFi and WebSocket connection
// ============================================================

void connectWiFi() {
  Serial.printf("[WIFI] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[WIFI] Connected. IP: %s, RSSI: %d dBm\n",
    WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

void connectWebSocket() {
  if (wsConnected) return;

  String url = String("wss://") + RELAY_HOST + RELAY_PATH + "?token=" + BRIDGE_TOKEN;
  Serial.printf("[WS] Connecting to %s...\n", RELAY_HOST);

  // For production: enable SSL certificate verification
  // wsClient.setCACert(root_ca);

  bool connected = wsClient.connect(url);
  if (!connected) {
    Serial.printf("[WS] Connection failed. Retrying in %lu ms\n", reconnectDelay);
    delay(reconnectDelay);
    reconnectDelay = min(reconnectDelay * 2, RECONNECT_MAX_MS);
  }
}

// ============================================================
// Arduino setup and loop
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== APP — ESP-32 Sensor Hub ===");

  // Hardware setup
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  digitalWrite(LED_PIN, LOW);
  dht.begin();

  // Network
  connectWiFi();

  // WebSocket
  wsClient.onMessage(onMessage);
  wsClient.onEvent(onEvent);
  connectWebSocket();
}

void loop() {
  // Maintain WebSocket connection
  if (wsConnected) {
    wsClient.poll();
  }

  // Reconnect if needed
  if (!wsConnected && WiFi.status() == WL_CONNECTED) {
    connectWebSocket();
  }

  // Reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] Connection lost, reconnecting...");
    connectWiFi();
  }

  // Heartbeat ping
  if (wsConnected && millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    wsClient.ping();
    lastHeartbeat = millis();
  }

  // Periodic sensor reporting
  if (wsConnected && millis() - lastSensorReport >= SENSOR_INTERVAL_MS) {
    lastTemperature = dht.readTemperature();
    lastHumidity = dht.readHumidity();
    if (isnan(lastTemperature)) lastTemperature = 0.0;
    if (isnan(lastHumidity)) lastHumidity = 0.0;

    wsClient.send(buildSensorEvent());
    Serial.printf("[SENSOR] Reported: %.1f°C, %.1f%% humidity\n",
      lastTemperature, lastHumidity);
    lastSensorReport = millis();
  }

  // Button press detection (simple debounce)
  bool buttonState = digitalRead(BUTTON_PIN);
  if (buttonState == LOW && lastButtonState == HIGH) {
    Serial.println("[BUTTON] Pressed");
    if (wsConnected) {
      JsonDocument doc;
      doc["type"] = "sensor_event";
      doc["id"] = makeId();
      doc["sensor"] = "button";
      JsonObject value = doc["value"].to<JsonObject>();
      value["button"] = "pressed";
      doc["trigger"] = "event";
      doc["timestamp"] = millis();
      String output;
      serializeJson(doc, output);
      wsClient.send(output);
    }
    delay(50);  // Simple debounce
  }
  lastButtonState = buttonState;

  delay(10);  // Yield to watchdog
}
