/**
 * Agent Presentation Protocol (APP) — Arduino UNO R4 WiFi Headless Bridge
 *
 * Connects an Arduino UNO R4 WiFi to an APP relay as a headless device.
 * Demonstrates LED control (built-in + LED matrix), analog sensor reading,
 * and device_action handling.
 *
 * DISCLAIMER: This code is provided as-is for reference only.
 * See the top-level README for the full disclaimer.
 *
 * Board: Arduino UNO R4 WiFi
 *   - Built-in LED on pin 13
 *   - 12x8 LED matrix (accessed via Arduino_LED_Matrix library)
 *   - Built-in WiFi (ESP32-S3 coprocessor)
 *
 * Hardware (optional):
 *   - Analog sensor (potentiometer, photoresistor, etc.) on A0
 *   - External LED on pin 9 (PWM capable)
 *   - Push button on pin 7 (to GND, internal pull-up)
 *
 * Required libraries:
 *   - ArduinoWebsockets by Gil Maimon (or ArduinoHttpClient)
 *   - ArduinoJson by Benoit Blanchon
 *   - WiFiS3 (included with UNO R4 board package)
 */

#include <WiFiS3.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

// Uncomment if you want to use the LED matrix
// #include <Arduino_LED_Matrix.h>
// ArduinoLEDMatrix matrix;

// ============================================================
// CONFIGURATION
// ============================================================

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BRIDGE_TOKEN  = "YOUR_BRIDGE_TOKEN";
const char* RELAY_HOST    = "your-relay.example";
const char* RELAY_PATH    = "/ws/bridge";

const int LED_PIN    = 13;   // Built-in LED
const int PWM_PIN    = 9;    // External LED (PWM)
const int BUTTON_PIN = 7;
const int ANALOG_PIN = A0;

const unsigned long SENSOR_INTERVAL = 30000;
const unsigned long HEARTBEAT_INTERVAL = 25000;

// ============================================================
// Globals
// ============================================================

using namespace websockets;
WebsocketsClient client;

bool ledState = false;
bool lastButton = HIGH;
int analogValue = 0;
unsigned long lastSensor = 0;
unsigned long lastPing = 0;
unsigned long reconnectDelay = 1000;
bool wsConnected = false;

// ============================================================
// Protocol messages
// ============================================================

// 128-bit random hex string formatted UUID-style. The Renesas RA4M1
// has no `esp_random()`-style hardware RNG exposed in the standard
// Arduino API; this uses Arduino's `random()` seeded from analog noise
// in setup(). The v4 format-specific bits are not enforced — this id is
// a dedup/correlation key, not a security identifier.
String makeId() {
  char buf[37];
  // Combine two 16-bit halves per 32-bit word — random()'s upper bits
  // may be biased on some cores; sampling 16 bits at a time is safer.
  uint32_t r1 = ((uint32_t)random(0, 0x10000) << 16) | (uint32_t)random(0, 0x10000);
  uint32_t r2 = ((uint32_t)random(0, 0x10000) << 16) | (uint32_t)random(0, 0x10000);
  uint32_t r3 = ((uint32_t)random(0, 0x10000) << 16) | (uint32_t)random(0, 0x10000);
  uint32_t r4 = ((uint32_t)random(0, 0x10000) << 16) | (uint32_t)random(0, 0x10000);
  snprintf(buf, sizeof(buf), "%08lx-%04lx-%04lx-%04lx-%04lx%08lx",
           (unsigned long)r1,
           (unsigned long)(r2 >> 16),
           (unsigned long)(r2 & 0xffff),
           (unsigned long)(r3 >> 16),
           (unsigned long)(r3 & 0xffff),
           (unsigned long)r4);
  return String(buf);
}

String agentCard() {
  JsonDocument doc;
  doc["type"] = "agent_card";

  // SPEC §3.3: agent_card wraps the card document under a "card" key.
  JsonObject card = doc["card"].to<JsonObject>();
  card["protocol_version"] = "0.4";

  JsonObject agent = card["agent"].to<JsonObject>();
  agent["name"] = "Arduino UNO R4 WiFi";
  agent["version"] = "1.0.0";
  agent["description"] = "Arduino UNO R4 WiFi with LED and analog sensor";

  JsonObject device = card["device"].to<JsonObject>();
  device["type"] = "microcontroller";
  device["manufacturer"] = "Arduino";
  device["model"] = "UNO R4 WiFi";
  device["interaction_model"] = "headless";

  JsonObject status = device["status"].to<JsonObject>();
  status["led"] = ledState ? "on" : "off";
  status["analog_value"] = analogValue;
  status["analog_voltage"] = (analogValue / 1023.0) * 3.3;

  // Available actions (nested under device per SPEC §5.2)
  JsonArray actions = device["available_actions"].to<JsonArray>();

  // set_led
  JsonObject a1 = actions.add<JsonObject>();
  a1["id"] = "set_led";
  a1["name"] = "Set LED";
  a1["description"] = "Turn the built-in LED on or off";
  JsonArray p1 = a1["params"].to<JsonArray>();
  JsonObject p1s = p1.add<JsonObject>();
  p1s["name"] = "state";
  p1s["type"] = "string";
  p1s["required"] = true;
  JsonArray opts = p1s["options"].to<JsonArray>();
  opts.add("on"); opts.add("off"); opts.add("toggle");

  // set_brightness
  JsonObject a2 = actions.add<JsonObject>();
  a2["id"] = "set_brightness";
  a2["name"] = "Set Brightness";
  a2["description"] = "Set external LED brightness (0-255) on pin 9";
  JsonArray p2 = a2["params"].to<JsonArray>();
  JsonObject p2l = p2.add<JsonObject>();
  p2l["name"] = "level";
  p2l["type"] = "integer";
  p2l["required"] = true;
  p2l["min"] = 0;
  p2l["max"] = 255;

  // read_sensor
  JsonObject a3 = actions.add<JsonObject>();
  a3["id"] = "read_sensor";
  a3["name"] = "Read Sensor";
  a3["description"] = "Read the analog sensor value on A0";

  // blink_led
  JsonObject a4 = actions.add<JsonObject>();
  a4["id"] = "blink_led";
  a4["name"] = "Blink LED";
  a4["description"] = "Blink the LED a number of times";
  JsonArray p4 = a4["params"].to<JsonArray>();
  JsonObject p4c = p4.add<JsonObject>();
  p4c["name"] = "count";
  p4c["type"] = "integer";
  p4c["required"] = false;

  // Capabilities. Headless device: interaction_model="headless" plus
  // omitted input_accepts/output_modalities declares no direct human I/O.
  JsonObject caps = card["capabilities"].to<JsonObject>();
  caps["streaming"] = false;
  caps["emotions"].to<JsonArray>();  // empty array — no emotion support

  String out;
  serializeJson(doc, out);
  return out;
}

String sensorEvent(const char* trigger = "periodic") {
  JsonDocument doc;
  doc["type"] = "sensor_event";
  doc["id"] = makeId();
  doc["sensor"] = "analog";
  JsonObject value = doc["value"].to<JsonObject>();
  value["analog_value"] = analogValue;
  value["analog_voltage"] = (analogValue / 1023.0) * 3.3;
  value["led"] = ledState ? "on" : "off";
  value["uptime_ms"] = millis();
  doc["trigger"] = trigger;
  // UNO R4 has no real-time clock; timestamp is monotonic ms-since-boot.
  // See README "Protocol notes". Downstream consumers needing wall-clock
  // time should stamp it on receipt.
  doc["timestamp"] = millis();
  String out;
  serializeJson(doc, out);
  return out;
}

// ============================================================
// Action handlers
// ============================================================

void doSetLed(JsonObject& p) {
  String s = p["state"] | "toggle";
  if (s == "on") ledState = true;
  else if (s == "off") ledState = false;
  else ledState = !ledState;
  digitalWrite(LED_PIN, ledState ? HIGH : LOW);
}

void doSetBrightness(JsonObject& p) {
  int level = constrain(p["level"] | 0, 0, 255);
  analogWrite(PWM_PIN, level);
}

void doBlinkLed(JsonObject& p) {
  int n = constrain(p["count"] | 3, 1, 20);
  for (int i = 0; i < n; i++) {
    digitalWrite(LED_PIN, HIGH); delay(200);
    digitalWrite(LED_PIN, LOW);  delay(200);
  }
  digitalWrite(LED_PIN, ledState ? HIGH : LOW);
}

void doReadSensor() {
  analogValue = analogRead(ANALOG_PIN);
  if (wsConnected) client.send(sensorEvent());
}

// ============================================================
// WebSocket callbacks
// ============================================================

void onMsg(WebsocketsMessage msg) {
  JsonDocument doc;
  if (deserializeJson(doc, msg.data())) return;

  const char* type = doc["type"];
  if (!type || strcmp(type, "device_action") != 0) return;

  const char* action = doc["action"];
  JsonObject params = doc["parameters"].as<JsonObject>();

  if (strcmp(action, "set_led") == 0) doSetLed(params);
  else if (strcmp(action, "set_brightness") == 0) doSetBrightness(params);
  else if (strcmp(action, "blink_led") == 0) doBlinkLed(params);
  else if (strcmp(action, "read_sensor") == 0) doReadSensor();

  if (wsConnected) client.send(sensorEvent("event"));
}

void onEvt(WebsocketsEvent evt, String data) {
  if (evt == WebsocketsEvent::ConnectionOpened) {
    wsConnected = true;
    reconnectDelay = 1000;
    client.send(agentCard());
    doReadSensor();
    Serial.println("[WS] Connected");
  } else if (evt == WebsocketsEvent::ConnectionClosed) {
    wsConnected = false;
    Serial.println("[WS] Disconnected");
  }
}

// ============================================================
// Setup and loop
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("=== APP — Arduino UNO R4 WiFi ===");

  pinMode(LED_PIN, OUTPUT);
  pinMode(PWM_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  // matrix.begin();  // Uncomment if using LED matrix

  // Seed random() from analog noise on the unconnected sensor pin so
  // makeId() produces different ids on each boot.
  randomSeed(analogRead(ANALOG_PIN));

  Serial.print("[WIFI] Connecting");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.print("\n[WIFI] ");
  Serial.println(WiFi.localIP());

  client.onMessage(onMsg);
  client.onEvent(onEvt);

  String url = String("wss://") + RELAY_HOST + RELAY_PATH + "?token=" + BRIDGE_TOKEN;
  client.connect(url);
}

void loop() {
  if (wsConnected) client.poll();

  if (!wsConnected && WiFi.status() == WL_CONNECTED) {
    String url = String("wss://") + RELAY_HOST + RELAY_PATH + "?token=" + BRIDGE_TOKEN;
    if (!client.connect(url)) {
      delay(reconnectDelay);
      reconnectDelay = min(reconnectDelay * 2, (unsigned long)60000);
    }
  }

  if (wsConnected && millis() - lastPing >= HEARTBEAT_INTERVAL) {
    client.ping();
    lastPing = millis();
  }

  if (wsConnected && millis() - lastSensor >= SENSOR_INTERVAL) {
    analogValue = analogRead(ANALOG_PIN);
    client.send(sensorEvent());
    lastSensor = millis();
  }

  bool btn = digitalRead(BUTTON_PIN);
  if (btn == LOW && lastButton == HIGH && wsConnected) {
    JsonDocument doc;
    doc["type"] = "sensor_event";
    doc["id"] = makeId();
    doc["sensor"] = "button";
    doc["value"]["button"] = "pressed";
    doc["trigger"] = "event";
    doc["timestamp"] = millis();
    String out; serializeJson(doc, out);
    client.send(out);
    delay(50);
  }
  lastButton = btn;

  delay(10);
}
