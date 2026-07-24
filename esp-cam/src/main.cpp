// Simple blink test for breadboard power wiring check.
// No camera, no WiFi — minimum current draw.
#include <Arduino.h>

#define LED_PIN 33  // ESP32-CAM built-in status LED (active-low)

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // LED off
  Serial.println("\nBreadboard blink test started");
}

void loop() {
  digitalWrite(LED_PIN, LOW);   // LED on
  Serial.println("ON");
  delay(500);
  digitalWrite(LED_PIN, HIGH);  // LED off
  Serial.println("OFF");
  delay(500);
}
