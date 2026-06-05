/**
 * Agent Presentation Protocol (APP) — ESP-32 Headless Bridge (Arduino IDE)
 *
 * Same functionality as the PlatformIO version, packaged as a single
 * Arduino sketch for users who prefer the Arduino IDE.
 *
 * DISCLAIMER: This code is provided as-is for reference only.
 * See the top-level README for the full disclaimer.
 *
 * Board setup in Arduino IDE:
 *   1. File → Preferences → Additional Board Manager URLs:
 *      https://espressif.github.io/arduino-esp32/package_esp32_index.json
 *   2. Tools → Board → Board Manager → search "esp32" → Install
 *   3. Tools → Board → ESP32 Arduino → ESP32 Dev Module
 *
 * Required libraries (install via Library Manager):
 *   - ArduinoWebsockets by Gil Maimon
 *   - ArduinoJson by Benoit Blanchon
 *   - DHT sensor library by Adafruit
 *   - Adafruit Unified Sensor by Adafruit
 *
 * Hardware:
 *   - LED on GPIO 2 (built-in on most boards)
 *   - DHT22 on GPIO 4 (with 10kΩ pull-up)
 *   - Button on GPIO 15 (to GND, internal pull-up)
 */

#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <esp_system.h>  // esp_random()

// ============================================================
// CONFIGURATION
// ============================================================

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BRIDGE_TOKEN  = "YOUR_BRIDGE_TOKEN";
const char* RELAY_URL     = "wss://your-relay.example/ws/bridge";

const int LED_PIN    = 2;
const int BUTTON_PIN = 15;
const int DHT_PIN    = 4;

const unsigned long SENSOR_INTERVAL = 30000;
const unsigned long HEARTBEAT_INTERVAL = 25000;

// ============================================================
// Globals
// ============================================================

using namespace websockets;
WebsocketsClient client;
DHT dht(DHT_PIN, DHT22);

bool ledState = false;
bool lastButton = HIGH;
float temperature = 0.0;
float humidity = 0.0;
unsigned long lastSensor = 0;
unsigned long lastPing = 0;
unsigned long reconnectDelay = 1000;
bool connected = false;

// ============================================================
// Protocol messages
// ============================================================

// 128-bit random hex string formatted UUID-style. ESP-32 has no UUID
// library and the v4 format-specific bits are not enforced — this id is
// a dedup/correlation key, not a security identifier. See README
// "Protocol notes" for context.
String makeId() {
  char buf[37];
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

String agentCard() {
  JsonDocument doc;
  doc["type"] = "agent_card";

  // SPEC §3.3: agent_card wraps the card document under a "card" key.
  JsonObject card = doc["card"].to<JsonObject>();
  card["protocol_version"] = "0.4";

  JsonObject agent = card["agent"].to<JsonObject>();
  agent["name"] = "ESP-32 Sensor Hub";
  agent["version"] = "1.0.0";
  agent["description"] = "ESP-32 with LED, button, and DHT22";

  JsonObject device = card["device"].to<JsonObject>();
  device["type"] = "sensor_hub";
  device["manufacturer"] = "Espressif";
  device["model"] = "ESP-32";
  device["interaction_model"] = "headless";

  JsonObject status = device["status"].to<JsonObject>();
  status["led"] = ledState ? "on" : "off";
  status["temperature_c"] = temperature;
  status["humidity_pct"] = humidity;

  // Available actions (nested under device per SPEC §5.2)
  JsonArray actions = device["available_actions"].to<JsonArray>();

  JsonObject a1 = actions.add<JsonObject>();
  a1["id"] = "set_led";
  a1["name"] = "Set LED";
  a1["description"] = "Turn the LED on, off, or toggle it";
  JsonArray p1 = a1["params"].to<JsonArray>();
  JsonObject p1s = p1.add<JsonObject>();
  p1s["name"] = "state";
  p1s["type"] = "string";
  p1s["required"] = true;
  JsonArray opts = p1s["options"].to<JsonArray>();
  opts.add("on"); opts.add("off"); opts.add("toggle");

  JsonObject a2 = actions.add<JsonObject>();
  a2["id"] = "read_sensors";
  a2["name"] = "Read Sensors";
  a2["description"] = "Read temperature and humidity now";

  JsonObject a3 = actions.add<JsonObject>();
  a3["id"] = "blink_led";
  a3["name"] = "Blink LED";
  a3["description"] = "Blink the LED a number of times";
  JsonArray p3 = a3["params"].to<JsonArray>();
  JsonObject p3c = p3.add<JsonObject>();
  p3c["name"] = "count";
  p3c["type"] = "integer";
  p3c["required"] = false;
  p3c["min"] = 1;
  p3c["max"] = 20;

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
  doc["sensor"] = "environment";
  JsonObject value = doc["value"].to<JsonObject>();
  value["temperature_c"] = temperature;
  value["humidity_pct"] = humidity;
  value["led"] = ledState ? "on" : "off";
  value["uptime_ms"] = millis();
  value["wifi_rssi"] = WiFi.RSSI();
  doc["trigger"] = trigger;
  // ESP-32 has no real-time clock by default; timestamp is monotonic
  // ms-since-boot. See README "Protocol notes". Downstream consumers
  // needing wall-clock time should stamp it on receipt.
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

void doBlinkLed(JsonObject& p) {
  int n = constrain(p["count"] | 3, 1, 20);
  for (int i = 0; i < n; i++) {
    digitalWrite(LED_PIN, HIGH); delay(200);
    digitalWrite(LED_PIN, LOW);  delay(200);
  }
  digitalWrite(LED_PIN, ledState ? HIGH : LOW);
}

void doReadSensors() {
  temperature = dht.readTemperature();
  humidity = dht.readHumidity();
  if (isnan(temperature)) temperature = 0;
  if (isnan(humidity)) humidity = 0;
  if (connected) client.send(sensorEvent());
}

// ============================================================
// WebSocket callbacks
// ============================================================

void onMsg(WebsocketsMessage msg) {
  JsonDocument doc;
  if (deserializeJson(doc, msg.data())) return;

  const char* type = doc["type"];
  if (!type) return;

  if (strcmp(type, "device_action") == 0) {
    const char* action = doc["action"];
    JsonObject params = doc["parameters"].as<JsonObject>();

    if (strcmp(action, "set_led") == 0) doSetLed(params);
    else if (strcmp(action, "blink_led") == 0) doBlinkLed(params);
    else if (strcmp(action, "read_sensors") == 0) doReadSensors();

    // Report updated state
    if (connected) client.send(sensorEvent("event"));
  }
}

void onEvt(WebsocketsEvent evt, String data) {
  if (evt == WebsocketsEvent::ConnectionOpened) {
    connected = true;
    reconnectDelay = 1000;
    client.send(agentCard());
    doReadSensors();
    Serial.println("[WS] Connected, Agent Card sent");
  } else if (evt == WebsocketsEvent::ConnectionClosed) {
    connected = false;
    Serial.println("[WS] Disconnected");
  }
}

// ============================================================
// Connection
// ============================================================

void connectWS() {
  String url = String(RELAY_URL) + "?token=" + BRIDGE_TOKEN;
  if (!client.connect(url)) {
    delay(reconnectDelay);
    reconnectDelay = min(reconnectDelay * 2, (unsigned long)60000);
  }
}

// ============================================================
// Arduino entry points
// ============================================================

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  dht.begin();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WIFI] Connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\n[WIFI] %s\n", WiFi.localIP().toString().c_str());

  client.onMessage(onMsg);
  client.onEvent(onEvt);
  connectWS();
}

void loop() {
  if (connected) client.poll();
  if (!connected && WiFi.status() == WL_CONNECTED) connectWS();
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); delay(5000); }

  if (connected && millis() - lastPing >= HEARTBEAT_INTERVAL) {
    client.ping();
    lastPing = millis();
  }

  if (connected && millis() - lastSensor >= SENSOR_INTERVAL) {
    temperature = dht.readTemperature();
    humidity = dht.readHumidity();
    if (isnan(temperature)) temperature = 0;
    if (isnan(humidity)) humidity = 0;
    client.send(sensorEvent());
    lastSensor = millis();
  }

  bool btn = digitalRead(BUTTON_PIN);
  if (btn == LOW && lastButton == HIGH && connected) {
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
