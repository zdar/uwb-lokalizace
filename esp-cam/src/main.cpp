// WiFi-only test firmware, no camera init.
// Tests whether the board runs stable on the new router/credentials.
#include <Arduino.h>
#include <WiFi.h>
#include "wifi_secrets.h"

#define LED_PIN 33  // built-in red LED (active-low)

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  delay(500);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // off

  Serial.println("\n--- WiFi-only test (no camera) ---");
  Serial.println("Measure 3.3 V pin during WiFi connect.");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);

  Serial.print("Connecting to ");
  Serial.print(WIFI_SSID);
  Serial.print(" ");
  while (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED_PIN, LOW);   // on
    delay(250);
    digitalWrite(LED_PIN, HIGH);  // off
    delay(250);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
  Serial.println("WiFi is up. Watch 3.3 V for 30 seconds.");
}

void loop() {
  digitalWrite(LED_PIN, LOW);
  delay(500);
  digitalWrite(LED_PIN, HIGH);
  delay(500);

  static unsigned long last = 0;
  unsigned long now = millis();
  if (now - last >= 5000) {
    last = now;
    Serial.print("WiFi status: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? "connected" : "disconnected");
    Serial.print(" RSSI: ");
    Serial.println(WiFi.RSSI());
  }
}
