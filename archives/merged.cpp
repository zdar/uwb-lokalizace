/*
For ESP32S3 UWB AT Demo - MERGED FIRMWARE
Anchor + Tag combined with role switching via AT command

Use 2.0.0    Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0    SPI
Use 2.5.7    Adafruit_SSD1306

Phase 1: Role-Switching Logic
AT+ROLE=0   -> Switch to TAG mode
AT+ROLE=1   -> Switch to ANCHOR mode
AT+ROLE?    -> Query current role
*/

// User config  ------------------------------------------

#define UWB_INDEX 0
#define UWB_TAG_COUNT 5

// Define the built-in BOOT button pin
#define BUTTON_PIN 0

// EEPROM settings
#define EEPROM_SIZE 512
#define ROLE_ADDRESS 0  // Address to store role (0=TAG, 1=ANCHOR)

// User config end  ------------------------------------------

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>
#include <EEPROM.h>

#define SERIAL_LOG Serial
#define SERIAL_AT mySerial2

HardwareSerial SERIAL_AT(2);

// ESP32S3
#define RESET 16

#define IO_RXD2 18
#define IO_TXD2 17

#define I2C_SDA 39
#define I2C_SCL 38

Adafruit_SSD1306 display(128, 64, &Wire, -1);

// --- Function Prototypes ---
void logoshow();
String sendData(String command, const int timeout, boolean debug);
String config_cmd();
String cap_cmd();
void processATCommand(String command);
uint8_t loadRole();
void saveRole(uint8_t role);
void configureUWB();
void displayRoleScreen(uint8_t role);
void displayReadyScreen();
// --------------------------------------------

// Global variables
uint8_t currentRole = 0;  // 0=TAG, 1=ANCHOR

// Variables for debounce (so one press doesn't count as 50)
unsigned long lastDebounceTime = 0;  
unsigned long debounceDelay = 200;    
bool reportingState = true; // Keep track of whether the firehose is ON or OFF


void setup()
{
    EEPROM.begin(EEPROM_SIZE);
    
    pinMode(RESET, OUTPUT);
    digitalWrite(RESET, HIGH);

    SERIAL_LOG.begin(115200);

    SERIAL_LOG.println(F("Hello! ESP32-S3 AT command V1.0 Test - MERGED"));
    SERIAL_AT.begin(115200, SERIAL_8N1, IO_RXD2, IO_TXD2);

    SERIAL_AT.print("AT\r\n"); 
    
    Wire.begin(I2C_SDA, I2C_SCL);
    delay(1000);
    
    // SSD1306_SWITCHCAPVCC = generate display voltage from 3.3V internally
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
    { 
        SERIAL_LOG.println(F("SSD1306 allocation failed"));
        for (;;)
            ; // Don't proceed, loop forever
    }
    display.clearDisplay();

    // Load saved role from EEPROM
    currentRole = loadRole();
    SERIAL_LOG.print(F("Loaded role from EEPROM: "));
    SERIAL_LOG.println(currentRole);

    logoshow();
    displayRoleScreen(currentRole);

    sendData("AT?", 2000, 1);

    // Configure UWB based on current role
    configureUWB();
    
    // Show completion screen
    displayReadyScreen();
    
    // Show role + ID again after ready
    logoshow();

    // Set up the BOOT button with the internal pull-up resistor
    pinMode(BUTTON_PIN, INPUT_PULLUP); 

    SERIAL_LOG.println(F("===================================="));
    SERIAL_LOG.println(F("MERGED FIRMWARE READY"));
    if (currentRole == 0) {
        SERIAL_LOG.println(F("MODE: TAG"));
    } else {
        SERIAL_LOG.println(F("MODE: ANCHOR"));
        SERIAL_LOG.println(F("PRESS THE 'BOOT' BUTTON TO TOGGLE REPORTING! "));
    }
    SERIAL_LOG.println(F("AT+ROLE=0  -> Switch to TAG"));
    SERIAL_LOG.println(F("AT+ROLE=1  -> Switch to ANCHOR"));
    SERIAL_LOG.println(F("AT+ROLE?   -> Query role"));
    SERIAL_LOG.println(F("===================================="));
}

void loop()
{
    // 1. Check the physical BOOT button (in both roles)
    if (digitalRead(BUTTON_PIN) == LOW) {
        
        // Debounce: Only trigger if enough time has passed
        if ((millis() - lastDebounceTime) > debounceDelay) {
            
            // Toggle the state
            reportingState = !reportingState; 
            
            if (reportingState == false) {
                SERIAL_LOG.println(F("\n--- BUTTON PRESSED: TURNING REPORTING OFF ---"));
                SERIAL_AT.print("AT+SETRPT=0\r\n");
            } else {
                SERIAL_LOG.println(F("\n--- BUTTON PRESSED: TURNING REPORTING ON ---"));
                SERIAL_AT.print("AT+SETRPT=1\r\n");
            }
            
            lastDebounceTime = millis(); // Reset the debounce timer
        }
    }

    // 2. Normal Keyboard Passthrough (with AT command interception)
    while (SERIAL_LOG.available() > 0)
    {
        char c = SERIAL_LOG.read();
        
        // Check if this is an AT command
        if (c == 'A') {
            String atCmd = "";
            atCmd += c;
            
            // Read the rest of the line
            unsigned long timeout = millis() + 100;
            while (millis() < timeout && SERIAL_LOG.available() > 0) {
                c = SERIAL_LOG.read();
                if (c == '\r' || c == '\n') {
                    break;
                }
                atCmd += c;
            }
            
            // Check if it's a ROLE command
            if (atCmd.startsWith("AT+ROLE")) {
                processATCommand(atCmd);
            } else {
                // Pass through to UWB module
                SERIAL_AT.write(atCmd.c_str(), atCmd.length());
                SERIAL_AT.write('\r');
                SERIAL_AT.write('\n');
            }
        } else {
            SERIAL_AT.write(c);
        }
        yield();
    }
    
    // 3. Pass UWB module output directly to the serial monitor
    while (SERIAL_AT.available() > 0)
    {
        SERIAL_LOG.write(SERIAL_AT.read());
        yield();
    }
}

// SSD1306
void logoshow(void)
{
    display.clearDisplay();
    display.setTextSize(1);              // Normal 1:1 pixel scale
    display.setTextColor(SSD1306_WHITE); // Draw white text
    display.setCursor(0, 0);             // Start at top-left corner
    display.println(F("MaUWB DW3000"));

    display.setCursor(0, 20); 

    display.setTextSize(2);
    String temp = "";
    
    if (currentRole == 0) {
        temp = temp + "T" + UWB_INDEX;
    } else {
        temp = temp + "A" + UWB_INDEX;
    }
    temp = temp + "   6.8M";
    display.println(temp);

    display.setCursor(0, 40);
    temp = "Total: ";
    temp = temp + UWB_TAG_COUNT;
    display.println(temp);

    display.display();
    delay(2000);
}

void displayRoleScreen(uint8_t role)
{
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 10);
    
    if (role == 0) {
        display.println(F("MODE: TAG"));
    } else {
        display.println(F("MODE: ANCHOR"));
    }
    
    display.setTextSize(1);
    display.setCursor(0, 40);
    display.println(F("Configuring..."));
    
    display.display();
    delay(1500);
}

void displayReadyScreen()
{
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 10);
    display.println(F("READY!"));
    
    display.setTextSize(1);
    display.setCursor(0, 35);
    if (currentRole == 0) {
        display.println(F("TAG Mode Active"));
    } else {
        display.println(F("ANCHOR Mode Active"));
    }
    
    display.setCursor(0, 50);
    display.println(F("Ready to operate..."));
    
    display.display();
    delay(2000);
}

String sendData(String command, const int timeout, boolean debug)
{
    String response = "";
    
    // FIXED: Appends the proper backslash carriage return + line feed
    command = command + "\r\n"; 

    SERIAL_LOG.print(command);
    SERIAL_AT.print(command); // Changed from println to print so it doesn't double up

    long int time = millis();

    while ((time + timeout) > millis())
    {
        while (SERIAL_AT.available())
        {
            // The esp has data so display its output to the serial window
            char c = SERIAL_AT.read(); // read the next character.
            response += c;
        }
    }

    if (debug)
    {
        SERIAL_LOG.print(response);
    }

    return response;                
}

String config_cmd()
{
    String temp = "AT+SETCFG=";
    temp = temp + UWB_INDEX;
    temp = temp + ",";
    temp = temp + currentRole;  // 0=TAG, 1=ANCHOR
    temp = temp + ",1";
    temp = temp + ",1";
    return temp;
}

String cap_cmd()
{
    String temp = "AT+SETCAP=";
    temp = temp + UWB_TAG_COUNT;
    temp = temp + ",10";
    temp = temp + ",1";
    return temp;
}

// ============== ROLE MANAGEMENT ==============

uint8_t loadRole()
{
    uint8_t role = EEPROM.read(ROLE_ADDRESS);
    // Validate: role should be 0 or 1
    if (role != 0 && role != 1) {
        return 0;  // Default to TAG mode
    }
    return role;
}

void saveRole(uint8_t role)
{
    if (role == 0 || role == 1) {
        EEPROM.write(ROLE_ADDRESS, role);
        EEPROM.commit();
    }
}

void configureUWB()
{
    sendData("AT?", 2000, 1);
    
    if (currentRole == 0) {
        // TAG mode configuration
        SERIAL_LOG.println(F(">>> Configuring as TAG"));
        sendData("AT+RESTORE", 5000, 1);
    } else {
        // ANCHOR mode configuration
        SERIAL_LOG.println(F(">>> Configuring as ANCHOR"));
    }

    sendData(config_cmd(), 2000, 1);
    sendData(cap_cmd(), 2000, 1);
    
    if (reportingState) {
        sendData("AT+SETRPT=1", 2000, 1);
    } else {
        sendData("AT+SETRPT=0", 2000, 1);
    }
    sendData("AT+SAVE", 2000, 1);
    sendData("AT+RESTART", 2000, 1);
}

void processATCommand(String command)
{
    command.trim();
    command.toUpperCase();
    
    SERIAL_LOG.println(F("\n=== PROCESSING CUSTOM AT COMMAND ==="));
    SERIAL_LOG.println(command);
    
    if (command.startsWith("AT+ROLE?")) {
        // Query current role
        SERIAL_LOG.print(F("Current Role: "));
        if (currentRole == 0) {
            SERIAL_LOG.println(F("TAG (0)"));
        } else {
            SERIAL_LOG.println(F("ANCHOR (1)"));
        }
        return;
    }
    
    if (command.startsWith("AT+ROLE=")) {
        // Extract the role value
        String valueStr = command.substring(8);  // Skip "AT+ROLE="
        valueStr.trim();
        
        int newRole = valueStr.toInt();
        
        if (newRole == 0 || newRole == 1) {
            if (newRole != currentRole) {
                SERIAL_LOG.print(F("Switching from "));
                SERIAL_LOG.print(currentRole);
                SERIAL_LOG.print(F(" to "));
                SERIAL_LOG.println(newRole);
                
                currentRole = newRole;
                saveRole(currentRole);
                
                SERIAL_LOG.println(F("Role saved. Please restart the device."));
                displayRoleScreen(currentRole);
                
                // Optional: Auto-restart after a delay
                delay(2000);
                SERIAL_LOG.println(F("Auto-restarting..."));
                ESP.restart();
            } else {
                SERIAL_LOG.println(F("Already in this mode."));
            }
        } else {
            SERIAL_LOG.println(F("Invalid role. Use 0 (TAG) or 1 (ANCHOR)"));
        }
        return;
    }
    
    SERIAL_LOG.println(F("Unknown custom command"));
}
