#include <Arduino.h>
#include <BluetoothSerial.h>

BluetoothSerial SerialBT;

const int numModules = 5;
const int sensorPins[numModules] = {34, 35, 32, 33, 25}; // Analog pins on ESP32

void setup() {
  Serial.begin(115200);
  
  // Start Bluetooth device with a custom name
  SerialBT.begin("BMS-DeLorean-ESP32"); 
  Serial.println("Bluetooth device started. Ready to pair!");
}

void loop() {
  // Construct JSON payload containing only raw sensor data (no business logic/status)
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

  // Send raw data over Bluetooth Serial to the server/tablet
  SerialBT.print(jsonPayload);
  
  // Also print to Serial Monitor for local debugging
  Serial.print(jsonPayload);

  delay(3000); // Send telemetry every 3 seconds
}