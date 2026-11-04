#include <Arduino.h>

/*
 * COMMUNICATION MODE FLAG:
 * 1 -> Bluetooth Classic (SerialBT)
 * 2 -> Wi-Fi HTTP POST
 * 3 -> Wi-Fi MQTT Publish
 */
#define COMM_MODE 1

#if COMM_MODE == 1
#include <BluetoothSerial.h>
BluetoothSerial SerialBT;

#elif COMM_MODE == 2 || COMM_MODE == 3
#include <WiFi.h>
#include <HTTPClient.h>
#include <PubSubClient.h>

const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "http://YOUR_SERVER_IP:5000/api/telemetry";
const char* mqttServer = "broker.hivemq.com";
const int mqttPort = 1883;

WiFiClient espClient;
PubSubClient mqttClient(espClient);
#endif

const int numModules = 5;
const int sensorPins[numModules] = {34, 35, 32, 33, 25}; // Analog pins on ESP32

void setup() {
  Serial.begin(115200);

#if COMM_MODE == 1
  SerialBT.begin("BMS-DeLorean-ESP32");
  Serial.println("Bluetooth device started. Ready to pair!");

#elif COMM_MODE == 2 || COMM_MODE == 3
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected successfully.");

  #if COMM_MODE == 3
  mqttClient.setServer(mqttServer, mqttPort);
  #endif
#endif
}

void loop() {
  // Construct JSON payload with raw sensor data
  String jsonPayload = "{\n";
  jsonPayload += "  \"battery_id\": \"BP-1985-DELOREAN\",\n";
  jsonPayload += "  \"modules\": [\n";

  for (int i = 0; i < numModules; i++) {
    int rawValue = analogRead(sensorPins[i]);
    
    // Map analog reading to raw resistance values in milli-ohms
    float resistance = map(rawValue, 0, 4095, 10, 50);
    if (i == 2) {
      resistance = 85.5; // Simulated critical value for Module 3 (Challenge 1)[cite: 7]
    }

    jsonPayload += "    {\"id\": " + String(i + 1) + ", \"resistance_mohm\": " + String(resistance, 1) + "}";
    if (i < numModules - 1) {
      jsonPayload += ",";
    }
    jsonPayload += "\n";
  }

  jsonPayload += "  ]\n";
  jsonPayload += "}\n\n";

  // Execute transmission based on the active flag
#if COMM_MODE == 1
  // --- BLUETOOTH TRANSMISSION ---
  SerialBT.print(jsonPayload);
  Serial.print(jsonPayload);

#elif COMM_MODE == 2
  // --- HTTP POST TRANSMISSION ---
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");
    
    int httpResponseCode = http.POST(jsonPayload);
    if (httpResponseCode > 0) {
      Serial.print("HTTP POST Success, code: ");
      Serial.println(httpResponseCode);
    } else {
      Serial.print("HTTP POST Error: ");
      Serial.println(http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  }

#elif COMM_MODE == 3
  // --- MQTT TRANSMISSION ---
  if (!mqttClient.connected()) {
    while (!mqttClient.connected()) {
      Serial.print("Attempting MQTT connection...");
      if (mqttClient.connect("ESP32BMSClient")) {
        Serial.println("connected");
      } else {
        Serial.print("failed, rc=");
        Serial.print(mqttClient.state());
        delay(5000);
      }
    }
  }
  mqttClient.loop();
  mqttClient.publish("battery/bms/telemetry", jsonPayload.c_str());
  Serial.println("MQTT message published.");
#endif

  delay(3000); // Send data every 3 seconds
}