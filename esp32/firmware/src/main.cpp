// BMS émulé sur ESP32 pour le Battery Passport (défi 1).
//
// Toutes les 3 s : lit 5 entrées analogiques (une par module), les convertit en résistance
// interne (mΩ) et envoie un JSON en Wi-Fi au site : POST http://<IP du PC>:8000/api/telemetry.
// Aucune règle métier ici : le serveur décide de la santé (nominal, surveillance, critique).
//
// Démo : appuyer sur le bouton BOOT (GPIO 0) déclenche la dérive du module 3, qui monte
// mesure après mesure jusqu'au défaut (6,8 mΩ). Un nouvel appui le remet à l'état sain.
// Le même JSON part aussi en Bluetooth série et sur le moniteur série (débogage).

#include <Arduino.h>
#include <BluetoothSerial.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "secrets.h"  // WIFI_SSID, WIFI_PASS, SERVER_URL, DEVICE_TOKEN (voir secrets.example.h)

BluetoothSerial SerialBT;

const char* BATTERY_ID = "DLR-1985";          // la batterie de Doc dans le passeport
const char* DEVICE_ID  = "esp32-bms-delorean";
const int NUM_MODULES = 5;
const int SENSOR_PINS[NUM_MODULES] = {34, 35, 32, 33, 25};  // entrées analogiques
const int FAULTY_MODULE = 3;
const int BOOT_BUTTON = 0;
const int LED_PIN = 2;                         // LED intégrée : clignote à chaque envoi

// Modèle FC-85 : environ 1,0 mΩ neuf, maximum constructeur 2,0 mΩ par module
const float R_MIN_HEALTHY = 1.0;
const float R_SPAN_HEALTHY = 0.5;              // la lecture analogique ajoute 0 à 0,5 mΩ
const float R_FAULT = 6.8;                     // valeur atteinte par le module défaillant
const float FAULT_STEP = 0.9;                  // hausse par mesure pendant la dérive
const unsigned long PERIOD_MS = 3000;

bool faultOn = false;
float faultR = R_MIN_HEALTHY;
unsigned long lastSend = 0;

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int k = 0; k < 40 && WiFi.status() != WL_CONNECTED; k++) {
    delay(250);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf(" OK, IP %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println(" échec, nouvel essai au prochain cycle");
  }
}

float readModule(int k) {
  int raw = analogRead(SENSOR_PINS[k]);        // 0 à 4095
  float r = R_MIN_HEALTHY + (raw / 4095.0) * R_SPAN_HEALTHY;
  if (k + 1 == FAULTY_MODULE) {
    if (faultOn) faultR = min(R_FAULT, faultR + FAULT_STEP);
    else faultR = r;
    r = max(r, faultR);
  }
  return r;
}

String buildPayload() {
  String json = "{\"batteryId\":\"" + String(BATTERY_ID) + "\",\"source\":\"ESP32\",\"modules\":[";
  for (int k = 0; k < NUM_MODULES; k++) {
    float t = 24.0 + (temperatureRead() - 40.0) * 0.05;  // température puce, indicative
    json += "{\"id\":" + String(k + 1) + ",\"r_mohm\":" + String(readModule(k), 2) +
            ",\"t\":" + String(t, 1) + "}";
    if (k < NUM_MODULES - 1) json += ",";
  }
  json += "]}";
  return json;
}

void sendHttp(const String& json) {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(SERVER_URL);
  http.setTimeout(2500);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", DEVICE_ID);
  if (strlen(DEVICE_TOKEN) > 0) http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int code = http.POST(json);
  Serial.printf("POST %s -> %d\n", SERVER_URL, code);
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_BUTTON, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  analogReadResolution(12);
  SerialBT.begin("BMS-DeLorean-ESP32");
  connectWifi();
}

void loop() {
  // bouton BOOT : bascule la dérive du module 3 (anti-rebond simple)
  static bool lastBtn = HIGH;
  bool btn = digitalRead(BOOT_BUTTON);
  if (lastBtn == HIGH && btn == LOW) {
    faultOn = !faultOn;
    Serial.println(faultOn ? "Défaut module 3 : ON" : "Défaut module 3 : OFF");
    delay(30);
  }
  lastBtn = btn;

  if (millis() - lastSend < PERIOD_MS) return;
  lastSend = millis();

  connectWifi();
  String json = buildPayload();
  digitalWrite(LED_PIN, HIGH);
  sendHttp(json);
  SerialBT.println(json);
  Serial.println(json);
  digitalWrite(LED_PIN, LOW);
}
