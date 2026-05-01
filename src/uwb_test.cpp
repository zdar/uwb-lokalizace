#include <Arduino.h>

// On Makerfabs S3, the UWB module (STM32) is on internal pins 43 and 44
HardwareSerial UWB_Serial(1); 

void setup() {
    // 1. Connection to your PC
    Serial.begin(115200);
    while(!Serial); // Wait for monitor to open
    
    Serial.println("\n--- Makerfabs UWB Bridge Mode ---");
    Serial.println("Type 'AT' and press Enter to test.");

    // 2. Connection to the UWB 'Co-Processor' (STM32)
    // RX = 44, TX = 43
    UWB_Serial.begin(115200, SERIAL_8N1, 44, 43); 
}

void loop() {
    // Forward data from UWB module to your PC screen
    if (UWB_Serial.available()) {
        Serial.write(UWB_Serial.read());
    }
    
    // Forward data from your keyboard to the UWB module
    if (Serial.available()) {
        UWB_Serial.write(Serial.read());
    }
}