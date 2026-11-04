/*
  BMS émulé, Battery Passport (Hackathon ESILV x Capgemini, Défi 1)
  ESP32 sur Wokwi : mesure (simulée) tension + courant des 5 modules,
  calcule la résistance interne R = ΔV / I et publie en MQTT toutes les 2 s.
  Wokwi ne voit pas le PC local : lancer le site avec MQTT_HOST=broker.hivemq.com.

  Potentiomètre = dégradation du module 3 (tourner -> R monte -> alerte).
  LED rouge = au moins un module au-dessus du max constructeur.
*/
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---- À CHANGER : mettre un préfixe unique à votre équipe (même valeur dans le backend) ----
const char* TOPIC_PREFIX = "esilv-hack-2026/equipe-XX";

const char* WIFI_SSID  = "Wokwi-GUEST";
const char* WIFI_PASS  = "";
const char* MQTT_HOST  = "broker.hivemq.com";
const int   MQTT_PORT  = 1883;
const char* BATTERY_ID = "DLR-1985";

const int   NB_MODULES = 5;
const int   FAULTY     = 3;       // module défectueux
const float R_MAX      = 2.0;     // mΩ, max constructeur du FC-85 (pour la LED locale)
const float I_LOAD     = 12.0;    // A
const float V_OCV      = 3.70;    // V, tension à vide d'un module
const int   POT_PIN    = 34;
const int   LED_PIN    = 2;

float baseR[NB_MODULES] = {1.2, 1.3, 1.1, 1.2, 1.4};  // mΩ, modules sains (FC-85 neuf : 1,0)

WiFiClient net;
PubSubClient mqtt(net);

void connectWifi() {
  Serial.print("WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.println(" OK");
}

void connectMqtt() {
  while (!mqtt.connected()) {
    String id = "bms-" + String((uint32_t)esp_random(), HEX);
    if (mqtt.connect(id.c_str())) Serial.println("MQTT OK");
    else { Serial.print("MQTT erreur "); Serial.println(mqtt.state()); delay(1000); }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  analogReadResolution(12);
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(1024);
  connectMqtt();
}

void loop() {
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  static unsigned long last = 0;
  if (millis() - last < 2000) return;
  last = millis();

  float knob = analogRead(POT_PIN) / 4095.0;   // 0..1

  JsonDocument doc;
  doc["batteryId"] = BATTERY_ID;
  JsonArray mods = doc["modules"].to<JsonArray>();
  bool critical = false;

  for (int k = 0; k < NB_MODULES; k++) {
    float r = baseR[k] + random(-5, 5) / 100.0;
    if (k + 1 == FAULTY) r += knob * 6.0;            // dégradation pilotée par le potentiomètre
    float i     = I_LOAD + random(-20, 20) / 100.0;   // "capteur" de courant
    float vLoad = V_OCV - i * r / 1000.0;             // "capteur" de tension sous charge
    float rCalc = (V_OCV - vLoad) / i * 1000.0;       // R = ΔV / I  (mΩ)
    float t     = 25.0 + (rCalc - 1.2) * 2.0 + random(-5, 5) / 10.0;

    JsonObject m = mods.add<JsonObject>();
    m["id"]     = k + 1;
    m["v_ocv"]  = V_OCV;
    m["v"]      = round(vLoad * 10000) / 10000.0;
    m["i"]      = round(i * 100) / 100.0;
    m["r_mohm"] = round(rCalc * 100) / 100.0;
    m["t"]      = round(t * 10) / 10.0;
    if (rCalc > R_MAX) critical = true;
  }
  digitalWrite(LED_PIN, critical ? HIGH : LOW);

  char buf[1024];
  serializeJson(doc, buf, sizeof(buf));
  String topic = String(TOPIC_PREFIX) + "/battery/" + BATTERY_ID + "/telemetry";
  mqtt.publish(topic.c_str(), buf);
  Serial.println(buf);
}
