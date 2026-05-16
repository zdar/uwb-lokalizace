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

#define UWB_INDEX 3
#define UWB_TAG_COUNT 5

// Define the built-in BOOT button pin
#define BUTTON_PIN 0

// EEPROM settings
#define EEPROM_SIZE 512
#define ROLE_ADDRESS 0  // Address to store role (0=TAG, 1=ANCHOR)
#define SYSTEM_ROLE_ADDRESS 1 // Address to store system role (0=node, 1=ANL)
#define NETID_ADDRESS 2       // Address to store the 16-bit network ID
#define DEFAULT_NETID 1234

#define WIFI_PORT 50000
#define HEARTBEAT_INTERVAL 3000
#define AP_CHANNEL 6
#define WIFI_PASSWORD "rtlsnet12"
#define MAX_REGISTRY_ENTRIES 16
#define NODE_TIMEOUT_MS 10000  // Consider a node stale if no heartbeat for 10 seconds

// User config end  ------------------------------------------

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>
#include <EEPROM.h>
#include <WiFi.h>
#include <WiFiUdp.h>

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
uint8_t loadSystemRole();
void saveSystemRole(uint8_t role);
uint16_t loadNetworkId();
void saveNetworkId(uint16_t netId);
void configureUWB();
void wifiSetup();
void udpLoop();
void sendHeartbeat();
void handleUdpPacket();
void registerNode(IPAddress from);
String ssidForNetId(uint16_t netId);
String netIdString(uint16_t netId);
void displayRoleScreen(uint8_t role);
void displayReadyScreen();
void maybeEnterProvisioning();
void provisioningMenu();
int waitForButtonEvent(unsigned long timeout);
void showProvisioningScreen(uint8_t stage);
void monitorWifiHealth();
void updateWifiStatusDisplay();
void drawAnlDashboard();
void printRegistryTable();
// --------------------------------------------

// Global variables
uint8_t currentRole = 0;  // 0=TAG, 1=ANCHOR
uint8_t systemRole = 0;   // 0=node, 1=ANL
uint16_t networkId = DEFAULT_NETID;

WiFiUDP udp;
unsigned long lastHeartbeatTime = 0;
unsigned long lastWifiCheckTime = 0;
unsigned long wifiLostTime = 0;
bool wifiWasConnected = false;
const unsigned long WIFI_CHECK_INTERVAL = 5000;  // Check every 5 seconds
const unsigned long WIFI_RECONNECT_TIMEOUT = 30000;  // Try reconnect for 30s

struct NodeInfo {
    IPAddress ip;
    unsigned long lastSeen;
};
NodeInfo registry[MAX_REGISTRY_ENTRIES];
int registryCount = 0;

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

    // Load saved roles and network configuration from EEPROM
    currentRole = loadRole();
    systemRole = loadSystemRole();
    networkId = loadNetworkId();

    SERIAL_LOG.print(F("Loaded role from EEPROM: "));
    SERIAL_LOG.println(currentRole);
    SERIAL_LOG.print(F("Loaded system role: "));
    SERIAL_LOG.println(systemRole);
    SERIAL_LOG.print(F("Loaded network ID: "));
    SERIAL_LOG.println(networkId);

    pinMode(BUTTON_PIN, INPUT_PULLUP); 
    maybeEnterProvisioning();

    logoshow();
    displayRoleScreen(currentRole);

    sendData("AT?", 2000, 1);

    // Configure UWB based on current role and network
    configureUWB();

    // Start WiFi control plane after UWB configuration
    wifiSetup();
    
    // Show completion screen
    displayReadyScreen();
    
    // Show role + ID again after ready
    logoshow();

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

    udpLoop();
    monitorWifiHealth();
    printRegistryTable();

    // NEW: Show live ANL dashboard instead of just a static line
    if (systemRole == 1) {
        drawAnlDashboard();
    } else {
        updateWifiStatusDisplay();  // nodes keep the old bottom-line WiFi status
    }
}

// SSD1306
void logoshow(void)
{
    display.clearDisplay();
    display.setTextSize(1);              
    display.setTextColor(SSD1306_WHITE); 

    display.setTextSize(2);
    String temp = "";
    display.setCursor(0, 0);
    
    if (currentRole == 0) {
        temp = temp + "T" + UWB_INDEX;
    } else {
        temp = temp + "A" + UWB_INDEX;
    }
    temp = temp + "   6.8M";
    display.println(temp);

    display.setCursor(0, 24);
    display.setTextSize(1);

    display.print(F("FW: "));

    String dateStr = __DATE__;  // "MMM DD YYYY"
    String mon = dateStr.substring(0, 3);
    int m = 0;
    if (mon == "Jan") m = 1;
    else if (mon == "Feb") m = 2;
    else if (mon == "Mar") m = 3;
    else if (mon == "Apr") m = 4;
    else if (mon == "May") m = 5;
    else if (mon == "Jun") m = 6;
    else if (mon == "Jul") m = 7;
    else if (mon == "Aug") m = 8;
    else if (mon == "Sep") m = 9;
    else if (mon == "Oct") m = 10;
    else if (mon == "Nov") m = 11;
    else if (mon == "Dec") m = 12;

    String day = dateStr.substring(4, 6);
    day.trim();

    String year = dateStr.substring(dateStr.length() - 2);

    display.print(day);
    display.print("/");
    if (m < 10) display.print("0");
    display.print(m);
    display.print("/");
    display.print(year);

    String timeStr = __TIME__;
    if (timeStr.length() >= 5) {
        display.print(" ");
        display.println(timeStr.substring(0, 5));
    } else {
        display.println(timeStr);
    }

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
    display.setCursor(0, 0);
    display.println(F("READY!"));
    
    display.setTextSize(1);
    display.setCursor(0, 24);
    if (currentRole == 0) {
        display.println(F("TAG Mode Active"));
    } else {
        display.println(F("ANCHOR Mode Active"));
    }
    
    display.setCursor(0, 38);
    if (systemRole == 1) {
        display.print(F("ANL AP: "));
    } else {
        display.print(F("JOIN NET: "));
    }
    display.println(ssidForNetId(networkId));
    
    display.setCursor(0, 52);
    display.print(F("WiFi: "));
    if (systemRole == 1 || WiFi.status() == WL_CONNECTED) {
        display.println(F("OK"));
    } else {
        display.println(F("FAIL"));
    }
    
    display.display();
    delay(4000);
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

uint8_t loadSystemRole()
{
    uint8_t role = EEPROM.read(SYSTEM_ROLE_ADDRESS);
    if (role != 0 && role != 1) {
        return 0;
    }
    return role;
}

void saveSystemRole(uint8_t role)
{
    if (role == 0 || role == 1) {
        EEPROM.write(SYSTEM_ROLE_ADDRESS, role);
        EEPROM.commit();
    }
}

uint16_t loadNetworkId()
{
    uint16_t low = EEPROM.read(NETID_ADDRESS);
    uint16_t high = EEPROM.read(NETID_ADDRESS + 1);
    uint16_t value = (high << 8) | low;
    if (value < 1000 || value > 9999) {
        return DEFAULT_NETID;
    }
    return value;
}

void saveNetworkId(uint16_t netId)
{
    if (netId < 1000) {
        netId = DEFAULT_NETID;
    }
    EEPROM.write(NETID_ADDRESS, netId & 0xFF);
    EEPROM.write(NETID_ADDRESS + 1, (netId >> 8) & 0xFF);
    EEPROM.commit();
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
    sendData(String("AT+SETPAN=") + networkId, 2000, 1);
    
    if (reportingState) {
        sendData("AT+SETRPT=1", 2000, 1);
    } else {
        sendData("AT+SETRPT=0", 2000, 1);
    }
    sendData("AT+SAVE", 2000, 1);
    sendData("AT+RESTART", 2000, 1);
}

void wifiSetup()
{
    if (systemRole == 1) {
        String ssid = ssidForNetId(networkId);
        SERIAL_LOG.print(F("Starting ANL AP: "));
        SERIAL_LOG.println(ssid);
        WiFi.mode(WIFI_AP);
        WiFi.softAP(ssid.c_str(), WIFI_PASSWORD, AP_CHANNEL);
        IPAddress apIp = WiFi.softAPIP();
        SERIAL_LOG.print(F("AP IP: "));
        SERIAL_LOG.println(apIp);
    } else {
        String ssid = ssidForNetId(networkId);
        SERIAL_LOG.print(F("Joining network: "));
        SERIAL_LOG.println(ssid);

        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0, 0);
        display.println(F("JOINING WIFI"));
        display.setCursor(0, 18);
        display.print(F("SSID: "));
        display.println(ssid);
        display.setCursor(0, 36);
        display.println(F("Please wait..."));
        display.display();

        WiFi.mode(WIFI_STA);
        WiFi.disconnect(true, true);
        delay(100);

        int attempt = 0;
        const int maxAttempts = 4;
        while (attempt < maxAttempts && WiFi.status() != WL_CONNECTED) {
            SERIAL_LOG.print(F("WiFi attempt "));
            SERIAL_LOG.print(attempt + 1);
            SERIAL_LOG.println(F("..."));

            WiFi.begin(ssid.c_str(), WIFI_PASSWORD);
            unsigned long start = millis();
            while (millis() - start < 15000) {
                if (WiFi.status() == WL_CONNECTED) {
                    break;
                }
                delay(200);
            }
            if (WiFi.status() == WL_CONNECTED) {
                SERIAL_LOG.println(F("WiFi connected"));
                SERIAL_LOG.print(F("IP: "));
                SERIAL_LOG.println(WiFi.localIP());
                display.clearDisplay();
                display.setTextSize(1);
                display.setTextColor(SSD1306_WHITE);
                display.setCursor(0, 0);
                display.println(F("WIFI CONNECTED"));
                display.setCursor(0, 18);
                display.print(F("SSID: "));
                display.println(ssid);
                display.setCursor(0, 36);
                display.print(F("IP: "));
                display.println(WiFi.localIP());
                display.display();
                delay(4000);
                break;
            }
            attempt++;
            if (attempt < maxAttempts) {
                SERIAL_LOG.println(F("Retrying WiFi join..."));
                delay(2000);
            }
        }

        if (WiFi.status() != WL_CONNECTED) {
            SERIAL_LOG.println(F("WiFi join failed"));
            display.clearDisplay();
            display.setTextSize(1);
            display.setTextColor(SSD1306_WHITE);
            display.setCursor(0, 0);
            display.println(F("WIFI JOIN FAILED"));
            display.setCursor(0, 18);
            display.print(F("SSID: "));
            display.println(ssid);
            display.setCursor(0, 34);
            display.println(F("Check ANL NETID"));
            display.setCursor(0, 50);
            display.println(F("Restart to retry"));
            display.display();
            delay(5000);
        }
    }
    udp.begin(WIFI_PORT);
}

void udpLoop()
{
    if (systemRole == 1) {
        handleUdpPacket();
    } else if (WiFi.status() == WL_CONNECTED) {
        if (millis() - lastHeartbeatTime >= HEARTBEAT_INTERVAL) {
            sendHeartbeat();
            lastHeartbeatTime = millis();
        }
    }
}

void sendHeartbeat()
{
    String payload = String("HB,") + UWB_INDEX + "," + networkId;
    udp.beginPacket("192.168.4.1", WIFI_PORT);
    udp.write((const uint8_t *)payload.c_str(), payload.length());
    udp.endPacket();
    SERIAL_LOG.print(F("Heartbeat sent: "));
    SERIAL_LOG.println(payload);
}

void handleUdpPacket()
{
    int packetSize = udp.parsePacket();
    if (packetSize <= 0) {
        return;
    }

    char buffer[128];
    int len = udp.read(buffer, sizeof(buffer) - 1);
    if (len <= 0) {
        return;
    }
    buffer[len] = '\0';
    String payload = String(buffer);
    IPAddress remoteIp = udp.remoteIP();

    SERIAL_LOG.print(F("UDP packet from "));
    SERIAL_LOG.println(remoteIp);
    SERIAL_LOG.print(F("Payload: "));
    SERIAL_LOG.println(payload);

    if (payload.startsWith("HB,")) {
        registerNode(remoteIp);
        udp.beginPacket(remoteIp, udp.remotePort());
        udp.print(String("ACK,") + UWB_INDEX);
        udp.endPacket();
    }
}

void registerNode(IPAddress from)
{
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].ip == from) {
            registry[i].lastSeen = millis();
            return;
        }
    }
    if (registryCount < MAX_REGISTRY_ENTRIES) {
        registry[registryCount].ip = from;
        registry[registryCount].lastSeen = millis();
        registryCount++;
        SERIAL_LOG.print(F("Registered node: "));
        SERIAL_LOG.println(from);
    }
}

String ssidForNetId(uint16_t netId)
{
    char buf[24];
    sprintf(buf, "RTLS-NET-%04u", netId);
    return String(buf);
}

String netIdString(uint16_t netId)
{
    char buf[8];
    sprintf(buf, "%04u", netId);
    return String(buf);
}

void maybeEnterProvisioning()
{
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 10);
    display.println(F("HOLD BUTTON TO"));
    display.setCursor(0, 25);
    display.println(F("ENTER SETUP"));
    display.setCursor(0, 45);
    display.println(F("(2 sec)"));
    display.display();

    unsigned long start = millis();
    while (millis() - start < 3000) {
        if (digitalRead(BUTTON_PIN) == LOW) {
            unsigned long holdStart = millis();
            while (digitalRead(BUTTON_PIN) == LOW) {
                if (millis() - holdStart >= 800) {
                    provisioningMenu();
                    return;
                }
                delay(10);
            }
        }
        delay(10);
    }
}

void provisioningMenu()
{
    uint8_t stage = 0;
    bool done = false;

    while (!done) {
        showProvisioningScreen(stage);
        int event = waitForButtonEvent(10000);

        if (event == 1) {
            if (stage == 0) {
                systemRole = (systemRole == 1) ? 0 : 1;
            } else if (stage == 1) {
                networkId++;
                if (networkId > 9999) {
                    networkId = 1000;
                }
            }
        } else if (event == 2) {
            if (stage == 0) {
                stage = 1;
            } else {
                saveSystemRole(systemRole);
                saveNetworkId(networkId);
                display.clearDisplay();
                display.setTextSize(1);
                display.setTextColor(SSD1306_WHITE);
                display.setCursor(0, 10);
                display.println(F("PROVISION SAVED"));
                display.setCursor(0, 30);
                display.print(F("ROLE: "));
                display.println(systemRole == 1 ? F("ANL") : F("NODE"));
                display.setCursor(0, 45);
                display.print(F("NETID: "));
                display.println(netIdString(networkId));
                display.display();
                delay(3000);
                done = true;
            }
        }
    }
}

int waitForButtonEvent(unsigned long timeout)
{
    unsigned long start = millis();
    while (millis() - start < timeout) {
        if (digitalRead(BUTTON_PIN) == LOW) {
            unsigned long pressStart = millis();
            while (digitalRead(BUTTON_PIN) == LOW) {
                if (millis() - pressStart >= 800) {
                    while (digitalRead(BUTTON_PIN) == LOW) {
                        delay(10);
                    }
                    return 2;
                }
                delay(10);
            }
            return 1;
        }
        delay(10);
    }
    return 0;
}

void showProvisioningScreen(uint8_t stage)
{
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);

    if (stage == 0) {
        display.println(F("SET SYSTEM ROLE"));
        display.setCursor(0, 22);
        display.setTextSize(2);
        display.println(systemRole == 1 ? F("ANL") : F("NODE"));
        display.setTextSize(1);
        display.setCursor(0, 50);
        display.println(F("PRESS BTN TO TOGGLE"));
        display.setCursor(0, 58);
        display.println(F("HOLD TO NEXT"));
    } else {
        display.println(F("SET NETWORK ID"));
        display.setCursor(0, 22);
        display.setTextSize(2);
        display.println(netIdString(networkId));
        display.setTextSize(1);
        display.setCursor(0, 50);
        display.println(F("PRESS BTN TO INCREMENT"));
        display.setCursor(0, 58);
        display.println(F("HOLD TO SAVE"));
    }
    display.display();
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

void monitorWifiHealth()
{
    // ANL doesn't need WiFi health monitoring
    if (systemRole == 1) {
        return;
    }

    unsigned long now = millis();

    // Check WiFi status periodically
    if (now - lastWifiCheckTime < WIFI_CHECK_INTERVAL) {
        return;
    }
    lastWifiCheckTime = now;

    bool isConnected = (WiFi.status() == WL_CONNECTED);

    if (isConnected && !wifiWasConnected) {
        // WiFi just reconnected
        SERIAL_LOG.println(F("[WiFi] RECONNECTED!"));
        SERIAL_LOG.print(F("IP: "));
        SERIAL_LOG.println(WiFi.localIP());
        wifiWasConnected = true;
        wifiLostTime = 0;
    } else if (!isConnected && wifiWasConnected) {
        // WiFi just lost
        SERIAL_LOG.println(F("[WiFi] CONNECTION LOST - Starting reconnect..."));
        wifiWasConnected = false;
        wifiLostTime = now;

        String ssid = ssidForNetId(networkId);
        WiFi.begin(ssid.c_str(), WIFI_PASSWORD);
    } else if (!isConnected && !wifiWasConnected) {
        // WiFi is still disconnected
        unsigned long downtime = now - wifiLostTime;
        if (downtime > WIFI_RECONNECT_TIMEOUT) {
            SERIAL_LOG.print(F("[WiFi] Still disconnected after "));
            SERIAL_LOG.print(WIFI_RECONNECT_TIMEOUT / 1000);
            SERIAL_LOG.println(F("s - retrying..."));

            String ssid = ssidForNetId(networkId);
            WiFi.disconnect();
            delay(100);
            WiFi.begin(ssid.c_str(), WIFI_PASSWORD);
            wifiLostTime = now;  // Reset the timer
        }
    }
}

void updateWifiStatusDisplay()
{
    static unsigned long lastDisplayUpdate = 0;
    static bool lastDisplayedConnected = false;

    // Only update display every 2 seconds to avoid flicker
    if (millis() - lastDisplayUpdate < 2000) {
        return;
    }
    lastDisplayUpdate = millis();

    bool isConnected = (systemRole == 1 || WiFi.status() == WL_CONNECTED);

    // Don't redraw if status hasn't changed
    if (isConnected == lastDisplayedConnected) {
        return;
    }
    lastDisplayedConnected = isConnected;

    // Small status line at bottom of display
    display.fillRect(0, 48, 128, 16, SSD1306_BLACK);  // Clear status area
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 50);

    if (systemRole == 1) {
        display.println(F("ANL Running"));
    } else if (isConnected) {
        display.print(F("WiFi OK | "));
        display.println(WiFi.localIP());
    } else {
        display.println(F("WiFi LOST - Reconnecting..."));
    }

    display.display();

    // Also log it
    if (systemRole == 0) {
        SERIAL_LOG.print(F("[Display] WiFi Status: "));
        SERIAL_LOG.println(isConnected ? F("OK") : F("LOST"));
    }
}

void drawAnlDashboard()
{
    static unsigned long lastDashboardUpdate = 0;
    static int lastDisplayedCount = -1;

    // Only update display every 2 seconds to avoid flicker
    if (millis() - lastDashboardUpdate < 2000) {
        return;
    }
    lastDashboardUpdate = millis();

    // Count active nodes (not stale)
    int activeNodes = 0;
    unsigned long now = millis();
    for (int i = 0; i < registryCount; i++) {
        unsigned long age = now - registry[i].lastSeen;
        if (age < NODE_TIMEOUT_MS) {
            activeNodes++;
        }
    }

    // Don't redraw if count hasn't changed
    if (activeNodes == lastDisplayedCount) {
        return;
    }
    lastDisplayedCount = activeNodes;

    // Draw ANL dashboard at bottom
    display.fillRect(0, 48, 128, 16, SSD1306_BLACK);  // Clear status area
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 50);

    display.print(F("ANL | Connected: "));
    display.println(activeNodes);

    display.display();
    SERIAL_LOG.print(F("[ANL Dashboard] Active nodes: "));
    SERIAL_LOG.println(activeNodes);
}

void printRegistryTable()
{
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint < 5000) return;
    lastPrint = millis();

    if (systemRole != 1) return;  // Only ANL prints registry

    SERIAL_LOG.println(F("\n========== ANL REGISTRY =========="));
    unsigned long now = millis();
    for (int i = 0; i < registryCount; i++) {
        unsigned long age = now - registry[i].lastSeen;
        SERIAL_LOG.print(F("Node "));
        SERIAL_LOG.print(i);
        SERIAL_LOG.print(F(" | IP: "));
        SERIAL_LOG.print(registry[i].ip);
        SERIAL_LOG.print(F(" | Age(ms): "));
        SERIAL_LOG.print(age);
        SERIAL_LOG.println(age < NODE_TIMEOUT_MS ? F(" [OK]") : F(" [STALE]"));
    }
    SERIAL_LOG.println(F("=================================="));
}
