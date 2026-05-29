/*
For ESP32S3 UWB AT Demo - MERGED FIRMWARE
Identical binary on all nodes. Behavior set by provisioning:
- System Role: ANL (AP) or NODE (STA)
- UWB Role:    TAG (0) or ANCHOR (1) via AT+ROLE or EEPROM
- UWB_INDEX:   0..7 (must be UNIQUE per node, ANL can be any index)

Auto-calibration sequence (ANL only):
1. Picks next unfixed node, sends ROLE,0 -> becomes temp Tag.
2. Waits ~25 s for reboot + WiFi rejoin + UWB config.
3. Collects wireless RPT ranges for ~15 s (median filter).
4. Solves position:
   - 1 fixed anchor known -> place on X-axis at measured distance.
   - 2 fixed anchors known -> two-circle intersection, pick +Y.
   - 3+ fixed anchors known -> trilateration.
5. Stores coordinate, sends ROLE,1 -> back to Anchor.
6. Repeats until all nodes fixed.

Use 2.0.0    Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0    SPI
Use 2.5.7    Adafruit_SSD1306
*/

//!!!!! DEFAULT INDEX FOR FIRST BOOT !!!!!
// ANY index can be the ANL. Just pick unique numbers 0..7!
#define UWB_INDEX_DEFAULT 0
//!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

#define UWB_TAG_COUNT 8
#define MAX_CAL_SAMPLES 5

#define BUTTON_PIN 0

#define EEPROM_SIZE 512
#define ROLE_ADDRESS 0
#define SYSTEM_ROLE_ADDRESS 1
#define NETID_ADDRESS 2
#define INDEX_ADDRESS 4
#define DEFAULT_NETID 1234

#define WIFI_PORT 50000
#define HEARTBEAT_INTERVAL 3000
#define AP_CHANNEL 6
#define WIFI_PASSWORD "rtlsnet12"
#define MAX_REGISTRY_ENTRIES 16
#define NODE_TIMEOUT_MS 10000

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>
#include <EEPROM.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>
#include <ArduinoOTA.h>

#define SERIAL_LOG Serial
#define SERIAL_AT mySerial2

HardwareSerial SERIAL_AT(2);

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
uint8_t loadIndex();
void saveIndex(uint8_t idx);
void configureUWB();
void wifiSetup();
void udpLoop();
void sendHeartbeat();
void relayUwbLine(const char* line);
void handleIncomingUdp();
void autoCalibrateLoop();
void setNodePosition(IPAddress from, float x, float y);
void registerNode(IPAddress from, uint8_t nodeId, uint8_t nodeRole = 1);
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
bool getAnchorPos(uint8_t anchorId, float &x, float &y);
bool solveTrilateration2D(float r0, float r1, float r2,
                          uint8_t a0, uint8_t a1, uint8_t a2,
                          float &outX, float &outY);
void setupOTA();
void handleOTA();
// --------------------------------------------

// Global variables
uint8_t currentRole = 0;
uint8_t systemRole = 0;
uint16_t networkId = DEFAULT_NETID;
uint8_t uwbIndex = UWB_INDEX_DEFAULT;
bool otaEnabled = false;
unsigned long otaEnableTime = 0;
const unsigned long OTA_TIMEOUT_MS = 120000; // 2 minutes

WiFiUDP udp;
unsigned long lastHeartbeatTime = 0;
unsigned long lastWifiCheckTime = 0;
unsigned long wifiLostTime = 0;
bool wifiWasConnected = false;
const unsigned long WIFI_CHECK_INTERVAL = 5000;
const unsigned long WIFI_RECONNECT_TIMEOUT = 30000;

struct NodeInfo {
    IPAddress ip;
    unsigned long lastSeen;
    float x = 0.0f;
    float y = 0.0f;
    bool hasPos = false;
    uint8_t id = 255;
    uint8_t role = 1;
};
NodeInfo registry[MAX_REGISTRY_ENTRIES];
int registryCount = 0;

unsigned long lastDebounceTime = 0;
unsigned long debounceDelay = 200;
bool reportingState = true;

// Buffer for capturing UWB lines for wireless relay
char rangeLineBuf[256];
int rangeLineIdx = 0;

// ================== AUTO-CALIBRATION STATE ==================
struct {
    uint8_t targetId;          // UWB_INDEX being calibrated (255 = idle)
    uint8_t phase;             // 0=idle, 1=wait reboot, 2=collecting, 3=wait revert
    unsigned long timer;
    IPAddress targetIp;        // IP at the time ROLE,0 was sent (fallback)
    float samples[8][MAX_CAL_SAMPLES];
    uint8_t sampleCount[8];
} cal = { 255, 0, 0, IPAddress(), {{0}}, {0} };
// ============================================================

bool getAnchorPos(uint8_t anchorId, float &x, float &y)
{
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].id == anchorId && registry[i].hasPos) {
            x = registry[i].x;
            y = registry[i].y;
            return true;
        }
    }
    return false;
}

bool solveTrilateration2D(float r0, float r1, float r2,
                          uint8_t a0, uint8_t a1, uint8_t a2,
                          float &outX, float &outY)
{
    float x0, y0, x1, y1, x2, y2;
    if (!getAnchorPos(a0, x0, y0)) return false;
    if (!getAnchorPos(a1, x1, y1)) return false;
    if (!getAnchorPos(a2, x2, y2)) return false;

    float dx = x1 - x0;
    float dy = y1 - y0;
    float d  = sqrt(dx*dx + dy*dy);

    if (d <= 0.0f || d > r0 + r1 || d < fabs(r0 - r1)) return false;

    float a = (r0*r0 - r1*r1 + d*d) / (2.0f * d);
    float h = sqrt(max(r0*r0 - a*a, 0.0f));

    float xm = x0 + a * dx / d;
    float ym = y0 + a * dy / d;

    float rx = -dy * (h / d);
    float ry =  dx * (h / d);

    float xa = xm + rx, ya = ym + ry;
    float xb = xm - rx, yb = ym - ry;

    float da = sqrt((xa - x2)*(xa - x2) + (ya - y2)*(ya - y2));
    float db = sqrt((xb - x2)*(xb - x2) + (yb - y2)*(yb - y2));

    if (fabs(da - r2) < fabs(db - r2)) {
        outX = xa;  outY = ya;
    } else {
        outX = xb;  outY = yb;
    }
    return true;
}

// ==============================================================
// AUTO-CALIBRATION STATE MACHINE (runs only on ANL)
// ==============================================================
bool isNodeAlive(uint8_t nodeId)
{
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].id == nodeId && (millis() - registry[i].lastSeen) < NODE_TIMEOUT_MS)
            return true;
    }
    return false;
}

IPAddress getNodeIp(uint8_t nodeId)
{
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].id == nodeId && (millis() - registry[i].lastSeen) < NODE_TIMEOUT_MS)
            return registry[i].ip;
    }
    return IPAddress();
}

void commitCalibrationResult(uint8_t targetId, float x, float y)
{
    int idx = -1;
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].id == targetId) idx = i;
    }
    if (idx < 0) {
        SERIAL_LOG.println(F("[AUTO] target ID vanished from registry"));
        return;
    }
    registry[idx].x = x;
    registry[idx].y = y;
    registry[idx].hasPos = true;
    SERIAL_LOG.print(F("[AUTO] Node ID "));
    SERIAL_LOG.print(targetId);
    SERIAL_LOG.print(F(" fixed at "));
    SERIAL_LOG.print(x, 2);
    SERIAL_LOG.print(F(", "));
    SERIAL_LOG.println(y, 2);
}

float medianSample(uint8_t anchor)
{
    uint8_t n = cal.sampleCount[anchor];
    if (n == 0) return -1.0f;
    float s[MAX_CAL_SAMPLES];
    memcpy(s, cal.samples[anchor], n * sizeof(float));
    // insertion sort (n <= 5, so this is trivial)
    for (uint8_t i = 1; i < n; i++) {
        float key = s[i];
        int j = (int)i - 1;
        while (j >= 0 && s[j] > key) {
            s[j + 1] = s[j];
            j--;
        }
        s[j + 1] = key;
    }
    if (n % 2 == 1) return s[n / 2];
    return (s[n / 2 - 1] + s[n / 2]) / 2.0f;
}

void autoCalibrateLoop()
{
    const unsigned long ROLE_SWITCH_DELAY = 60000; // 60s: enough for UWB reconfig
    const unsigned long COLLECT_TIME      = 20000; // 20s: gather multiple samples

    if (systemRole != 1) return;

    switch (cal.phase) {
        case 0: {
            uint8_t candidate = 255;
            for (int i = 1; i < registryCount; i++) {
                if (!registry[i].hasPos && registry[i].id != 255 && registry[i].id != (uint8_t)uwbIndex) {
                    if (isNodeAlive(registry[i].id) && registry[i].role == 1) {
                        candidate = registry[i].id;
                        break;
                    }
                }
            }
            if (candidate == 255) return;

            cal.targetId = candidate;
            cal.phase = 1;
            cal.timer = millis();
            memset(cal.sampleCount, 0, sizeof(cal.sampleCount));
            memset(cal.samples, 0, sizeof(cal.samples));

            IPAddress ip = getNodeIp(candidate);
            cal.targetIp = ip; // remember for fallback

            SERIAL_LOG.print(F("[CAL] Target node ID "));
            SERIAL_LOG.print(candidate);
            SERIAL_LOG.print(F(" IP "));
            SERIAL_LOG.println(ip);

            if (ip != IPAddress()) {
                udp.beginPacket(ip, WIFI_PORT);
                udp.print("ROLE,0");
                udp.endPacket();
                SERIAL_LOG.println(F("[CAL] Sent ROLE,0 (Tag)"));
            } else {
                SERIAL_LOG.println(F("[CAL] IP not found, waiting..."));
            }
            break;
        }

        case 1: {
            // Node is rebooting and reconfiguring UWB. Just wait.
            if (millis() - cal.timer < ROLE_SWITCH_DELAY) return;
            memset(cal.sampleCount, 0, sizeof(cal.sampleCount));
            memset(cal.samples, 0, sizeof(cal.samples));
            cal.phase = 2;
            cal.timer = millis();
            SERIAL_LOG.println(F("[CAL] Window open, collecting RPT..."));
            break;
        }

        case 2: {
            if (millis() - cal.timer < COLLECT_TIME) return;

            float vr[8];
            uint8_t va[8];
            int vc = 0;

            for (int a = 0; a < 8; a++) {
                if (cal.sampleCount[a] == 0) continue;
                float r = medianSample((uint8_t)a);
                if (r <= 0.0f) continue;
                bool fixed = false;
                for (int ri = 0; ri < registryCount; ri++) {
                    if (registry[ri].id == (uint8_t)a && registry[ri].hasPos) {
                        fixed = true;
                        break;
                    }
                }
                if (fixed && vc < 8) {
                    va[vc] = (uint8_t)a;
                    vr[vc] = r;
                    vc++;
                }
            }

            SERIAL_LOG.print(F("[CAL] Median ranges from "));
            SERIAL_LOG.print(vc);
            SERIAL_LOG.println(F(" fixed anchors"));

            bool solved = false;
            float sx = 0, sy = 0;

            if (vc >= 3) {
                solved = solveTrilateration2D(vr[0], vr[1], vr[2],
                                              va[0], va[1], va[2],
                                              sx, sy);
            } else if (vc == 2) {
                float x0, y0, x1, y1;
                if (getAnchorPos(va[0], x0, y0) && getAnchorPos(va[1], x1, y1)) {
                    float dx = x1 - x0;
                    float dy = y1 - y0;
                    float d  = sqrt(dx*dx + dy*dy);
                    if (d > 0 && d < vr[0] + vr[1] && d > fabs(vr[0] - vr[1])) {
                        float a = (vr[0]*vr[0] - vr[1]*vr[1] + d*d) / (2.0f * d);
                        float h = sqrt(max(vr[0]*vr[0] - a*a, 0.0f));
                        float xm = x0 + a * dx / d;
                        float ym = y0 + a * dy / d;
                        float rx = -dy * (h / d);
                        float ry =  dx * (h / d);
                        float xa = xm + rx, ya = ym + ry;
                        float xb = xm - rx, yb = ym - ry;
                        sx = (ya >= yb) ? xa : xb;
                        sy = (ya >= yb) ? ya : yb;
                        solved = true;
                    }
                }
            } else if (vc == 1) {
                sx = vr[0];
                sy = 0.0f;
                solved = true;
            }

            if (solved) {
                commitCalibrationResult(cal.targetId, sx, sy);
            } else {
                SERIAL_LOG.println(F("[AUTO] Solve failed (geometry/noise)"));
            }

            // Use the IP we actually saw RPTs from; only fall back to registry if empty
            IPAddress ip = cal.targetIp;
            if (ip == IPAddress()) ip = getNodeIp(cal.targetId);
            if (ip != IPAddress()) {
                udp.beginPacket(ip, WIFI_PORT);
                udp.print("ROLE,1");
                udp.endPacket();
                SERIAL_LOG.println(F("[CAL] Sent ROLE,1 (Anchor)"));
            } else {
                SERIAL_LOG.println(F("[CAL] CRITICAL: no IP to send ROLE,1"));
            }

            cal.phase = 3;
            cal.timer = millis();
            break;
        }

        case 3: {
            // Wait for node to reboot back to Anchor.
            if (millis() - cal.timer < ROLE_SWITCH_DELAY) return;
            SERIAL_LOG.println(F("[CAL] Done, looking for next..."));
            cal.targetId = 255;
            cal.targetIp = IPAddress();
            cal.phase = 0;
            break;
        }
    }
}

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

    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
    {
        SERIAL_LOG.println(F("SSD1306 allocation failed"));
        for (;;);
    }
    display.clearDisplay();

    currentRole = loadRole();
    systemRole = loadSystemRole();
    networkId = loadNetworkId();
    uwbIndex = loadIndex();

    // Let currentRole stay exactly as saved in EEPROM.
    // If EEPROM is blank, loadRole defaults to 1 (Anchor) for safety.

    SERIAL_LOG.print(F("Loaded role from EEPROM: "));
    SERIAL_LOG.println(currentRole);
    SERIAL_LOG.print(F("Loaded system role: "));
    SERIAL_LOG.println(systemRole);
    SERIAL_LOG.print(F("Loaded network ID: "));
    SERIAL_LOG.println(networkId);
    SERIAL_LOG.print(F("Loaded UWB index: "));
    SERIAL_LOG.println(uwbIndex);

    pinMode(BUTTON_PIN, INPUT_PULLUP);
    maybeEnterProvisioning();

    logoshow();
    displayRoleScreen(currentRole);

    sendData("AT?", 2000, 1);

    configureUWB();
    wifiSetup();
    setupOTA();

    if (systemRole == 1) {
        registry[0].ip = WiFi.softAPIP();
        registry[0].lastSeen = millis();
        registry[0].x = 0.0f;
        registry[0].y = 0.0f;
        registry[0].hasPos = true;
        registry[0].id = (uint8_t)uwbIndex;
        registryCount = 1;

        SERIAL_LOG.print(F("ANL registered at (0.00, 0.00) with ID "));
        SERIAL_LOG.println(uwbIndex);
    }

    displayReadyScreen();
    logoshow();

    SERIAL_LOG.println(F("===================================="));
    SERIAL_LOG.println(F("MERGED FIRMWARE READY"));
    if (currentRole == 0) {
        SERIAL_LOG.println(F("MODE: TAG"));
    } else {
        SERIAL_LOG.println(F("MODE: ANCHOR"));
    }
    SERIAL_LOG.println(F("SHORT press  = toggle reporting (Anchor only)"));
    SERIAL_LOG.println(F("HOLD 2.5 sec = toggle TAG/ANCHOR + reboot"));
    SERIAL_LOG.println(F("===================================="));
}

void loop()
{
    // ==========================================
    // BOOT BUTTON: short press = toggle reporting (anchors only)
    //              long hold 2.5s = toggle TAG/ANCHOR and reboot
    // ==========================================
    static bool btnWasDown = false;
    static unsigned long btnDownT = 0;
    static bool roleToggleDone = false;

    bool btnNow = (digitalRead(BUTTON_PIN) == LOW);

    if (btnNow && !btnWasDown) {
        btnDownT = millis();
        btnWasDown = true;
        roleToggleDone = false;
    }

    if (btnWasDown) {
        if (btnNow) {
            unsigned long held = millis() - btnDownT;
            if (!roleToggleDone && held >= 2500) {
                roleToggleDone = true;
                uint8_t newRole = (currentRole == 0) ? 1 : 0;
                saveRole(newRole);
                display.clearDisplay();
                display.setTextSize(2);
                display.setTextColor(SSD1306_WHITE);
                display.setCursor(0, 18);
                display.println(newRole == 1 ? F("ANCHOR") : F("TAG"));
                display.setCursor(0, 42);
                display.setTextSize(1);
                display.println(F("Rebooting..."));
                display.display();
                delay(800);
                ESP.restart();
            }
        } else {
            unsigned long held = millis() - btnDownT;
            btnWasDown = false;
            if (!roleToggleDone && held >= debounceDelay) {
                if (currentRole == 1) {
                    reportingState = !reportingState;
                    if (reportingState) {
                        SERIAL_LOG.println(F("--- RPT ON ---"));
                        SERIAL_AT.print("AT+SETRPT=1\r\n");
                    } else {
                        SERIAL_LOG.println(F("--- RPT OFF ---"));
                        SERIAL_AT.print("AT+SETRPT=0\r\n");
                    }
                } else {
                    SERIAL_LOG.println(F("--- TAG: reporting locked ON ---"));
                }
            }
            roleToggleDone = false;
        }
    }
    // ==========================================

    while (SERIAL_LOG.available() > 0)
    {
        char c = SERIAL_LOG.read();
        if (c == 'A') {
            String atCmd = "";
            atCmd += c;
            unsigned long timeout = millis() + 100;
            while (millis() < timeout && SERIAL_LOG.available() > 0) {
                c = SERIAL_LOG.read();
                if (c == '\r' || c == '\n') break;
                atCmd += c;
            }
            if (atCmd.startsWith("AT+ROLE")) {
                processATCommand(atCmd);
            } else {
                SERIAL_AT.write(atCmd.c_str(), atCmd.length());
                SERIAL_AT.write('\r');
                SERIAL_AT.write('\n');
            }
        } else {
            SERIAL_AT.write(c);
        }
        yield();
    }

    while (SERIAL_AT.available() > 0)
    {
        char c = SERIAL_AT.read();
        SERIAL_LOG.write(c);

        if (rangeLineIdx < (int)sizeof(rangeLineBuf) - 1) {
            rangeLineBuf[rangeLineIdx++] = c;
        }

        if (c == '\n') {
            if (rangeLineIdx > 0) {
                int end = rangeLineIdx - 1;
                while (end >= 0 && (rangeLineBuf[end] == '\r' || rangeLineBuf[end] == '\n' || rangeLineBuf[end] == ' ')) {
                    rangeLineBuf[end] = '\0';
                    end--;
                }
                if (systemRole == 0 && currentRole == 0 && strncmp(rangeLineBuf, "AT+RANGE", 8) == 0) {
                    relayUwbLine(rangeLineBuf);
                }
                rangeLineIdx = 0;
            }
        }
        yield();
    }

    udpLoop();
    autoCalibrateLoop();
    monitorWifiHealth();
    printRegistryTable();
    handleOTA();

    if (systemRole == 1) {
        drawAnlDashboard();
    } else {
        updateWifiStatusDisplay();
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
        temp = temp + "T" + uwbIndex;
    } else {
        temp = temp + "A" + uwbIndex;
    }
    temp = temp + "   6.8M";
    display.println(temp);

    display.setCursor(0, 24);
    display.setTextSize(1);
    display.print(F("FW: "));

    String dateStr = __DATE__;
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
    command = command + "\r\n";
    SERIAL_LOG.print(command);
    SERIAL_AT.print(command);
    long int time = millis();
    while ((time + timeout) > millis())
    {
        while (SERIAL_AT.available())
        {
            char c = SERIAL_AT.read();
            response += c;
        }
    }
    if (debug) {
        SERIAL_LOG.print(response);
    }
    return response;
}

String config_cmd()
{
    String temp = "AT+SETCFG=";
    temp = temp + uwbIndex;
    temp = temp + ",";
    temp = temp + currentRole;
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

uint8_t loadRole()
{
    uint8_t role = EEPROM.read(ROLE_ADDRESS);
    if (role != 0 && role != 1) return 1;
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
    if (role != 0 && role != 1) return 0;
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
    if (value < 1000 || value > 9999) return DEFAULT_NETID;
    return value;
}

void saveNetworkId(uint16_t netId)
{
    if (netId < 1000) netId = DEFAULT_NETID;
    EEPROM.write(NETID_ADDRESS, netId & 0xFF);
    EEPROM.write(NETID_ADDRESS + 1, (netId >> 8) & 0xFF);
    EEPROM.commit();
}

uint8_t loadIndex()
{
    uint8_t idx = EEPROM.read(INDEX_ADDRESS);
    if (idx > 7) return UWB_INDEX_DEFAULT;
    return idx;
}

void saveIndex(uint8_t idx)
{
    if (idx <= 7) {
        EEPROM.write(INDEX_ADDRESS, idx);
        EEPROM.commit();
    }
}

void setupOTA()
{
    ArduinoOTA.onStart([]() {
        SERIAL_LOG.println(F("[OTA] Start"));
        display.clearDisplay();
        display.setTextSize(2);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0, 18);
        display.println(F("OTA UPDATE"));
        display.setCursor(0, 42);
        display.setTextSize(1);
        display.println(F("Flashing..."));
        display.display();
    });
    ArduinoOTA.onEnd([]() {
        SERIAL_LOG.println(F("[OTA] End"));
        display.clearDisplay();
        display.setTextSize(2);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0, 18);
        display.println(F("DONE"));
        display.setCursor(0, 42);
        display.setTextSize(1);
        display.println(F("Rebooting..."));
        display.display();
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        static int lastPct = -1;
        int pct = (progress * 100) / total;
        if (pct != lastPct && pct % 10 == 0) {
            lastPct = pct;
            SERIAL_LOG.print(F("[OTA] Progress: "));
            SERIAL_LOG.print(pct);
            SERIAL_LOG.println(F("%"));
            display.fillRect(0, 56, 128, 8, SSD1306_BLACK);
            display.setTextSize(1);
            display.setCursor(0, 56);
            display.print(pct);
            display.print(F("%"));
            display.display();
        }
    });
    ArduinoOTA.onError([](ota_error_t error) {
        SERIAL_LOG.print(F("[OTA] Error "));
        SERIAL_LOG.println(error);
        display.clearDisplay();
        display.setTextSize(2);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0, 18);
        display.println(F("OTA FAIL"));
        display.display();
    });
    ArduinoOTA.setPassword("rtlsota12");
    ArduinoOTA.begin();
    SERIAL_LOG.println(F("[OTA] Ready (password protected)"));
}

void handleOTA()
{
    if (otaEnabled) {
        ArduinoOTA.handle();
        if (millis() - otaEnableTime > OTA_TIMEOUT_MS) {
            otaEnabled = false;
            SERIAL_LOG.println(F("[OTA] Window expired"));
        }
    }
}

void configureUWB()
{
    sendData("AT?", 2000, 1);
    if (currentRole == 0) {
        SERIAL_LOG.println(F(">>> Configuring as TAG"));
        sendData("AT+RESTORE", 5000, 1);
    } else {
        SERIAL_LOG.println(F(">>> Configuring as ANCHOR"));
    }
    sendData(config_cmd(), 2000, 1);
    sendData(cap_cmd(), 2000, 1);
    sendData(String("AT+SETPAN=") + networkId, 2000, 1);

    if (currentRole == 0) {
        sendData("AT+SETRPT=1", 2000, 1);
    } else {
        if (reportingState) {
            sendData("AT+SETRPT=1", 2000, 1);
        } else {
            sendData("AT+SETRPT=0", 2000, 1);
        }
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
                if (WiFi.status() == WL_CONNECTED) break;
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
    handleIncomingUdp();

    if (systemRole == 0 && WiFi.status() == WL_CONNECTED) {
        if (millis() - lastHeartbeatTime >= HEARTBEAT_INTERVAL) {
            sendHeartbeat();
            lastHeartbeatTime = millis();
        }
    }
}

void sendHeartbeat()
{
    String payload = String("HB,") + uwbIndex + "," + currentRole + "," + networkId;
    udp.beginPacket("192.168.4.1", WIFI_PORT);
    udp.write((const uint8_t *)payload.c_str(), payload.length());
    udp.endPacket();
    SERIAL_LOG.print(F("Heartbeat sent: "));
    SERIAL_LOG.println(payload);
}

void relayUwbLine(const char* line)
{
    if (WiFi.status() != WL_CONNECTED) return;

    char pkt[280];
    snprintf(pkt, sizeof(pkt), "RPT,%s", line);

    udp.beginPacket("192.168.4.1", WIFI_PORT);
    udp.write((const uint8_t*)pkt, strlen(pkt));
    udp.endPacket();
}

void handleIncomingUdp()
{
    int packetSize = udp.parsePacket();
    if (packetSize <= 0) return;

    char buf[256];
    int len = udp.read(buf, sizeof(buf) - 1);
    if (len <= 0) return;
    buf[len] = '\0';

    IPAddress remoteIp = udp.remoteIP();
    uint16_t remotePort = udp.remotePort();

    // ---------- RPT: wireless range report (ANL only) ----------
    if (systemRole == 1 && len >= 4 && strncmp(buf, "RPT,", 4) == 0) {
        const char* rpt = buf + 4;

        const char* p = strstr(rpt, "tid:");
        if (!p) return;
        int tid = atoi(p + 4);

        p = strstr(rpt, "range:(");
        if (!p) return;
        p += 7;

        float ranges[8] = {0};
        int rc = 0;
        char tmp[12];
        int ti = 0;
        while (*p && rc < 8) {
            if (*p == '-' || (*p >= '0' && *p <= '9')) {
                if (ti < 11) tmp[ti++] = *p;
            } else if (*p == ',' || *p == ')') {
                if (ti > 0) {
                    tmp[ti] = '\0';
                    ranges[rc++] = (float)atoi(tmp);
                    ti = 0;
                }
                if (*p == ')') break;
            }
            p++;
        }

        p = strstr(rpt, "ancid:(");
        if (!p) return;
        p += 7;

        int ancids[8] = {-1};
        int ac = 0;
        ti = 0;
        while (*p && ac < 8) {
            if (*p == '-' || (*p >= '0' && *p <= '9')) {
                if (ti < 11) tmp[ti++] = *p;
            } else if (*p == ',' || *p == ')') {
                if (ti > 0) {
                    tmp[ti] = '\0';
                    ancids[ac++] = atoi(tmp);
                    ti = 0;
                }
                if (*p == ')') break;
            }
            p++;
        }

        // Register / keepalive
        uint8_t knownRole = 1; // default anchor
        for (int i = 0; i < registryCount; i++) {
            if (registry[i].ip == remoteIp) {
            knownRole = registry[i].role;
            break;
    }
}
registerNode(remoteIp, (uint8_t)tid, knownRole);

        // Store samples for median filtering during calibration
        if (cal.targetId != 255 && (uint8_t)tid == cal.targetId) {
            cal.targetIp = remoteIp; // update target IP in case it changed
            
            int pairs = (rc < ac) ? rc : ac;
            for (int j = 0; j < pairs; j++) {
                if (ancids[j] >= 0 && ancids[j] < 8) {
                    uint8_t a = (uint8_t)ancids[j];
                    if (cal.sampleCount[a] < MAX_CAL_SAMPLES) {
                        cal.samples[a][cal.sampleCount[a]++] = ranges[j];
                    }
                }
            }
        }

        // (RPT logging disabled to keep serial clean)
        // SERIAL_LOG.print(F("[RPT] tid="));
        // SERIAL_LOG.print(tid);
        // SERIAL_LOG.print(F(" ranges="));
        // SERIAL_LOG.print(rc);
        // SERIAL_LOG.print(F(" ancids="));
        // SERIAL_LOG.println(ac);

        // ---------- Option C: solve position on ANL and broadcast ----------
        {
            float vr[8];
            uint8_t va[8];
            int vc = 0;
            int pairs = (rc < ac) ? rc : ac;
            for (int j = 0; j < pairs; j++) {
                if (ancids[j] >= 0 && ancids[j] < 8 && ranges[j] > 0) {
                    uint8_t a = (uint8_t)ancids[j];
                    bool fixed = false;
                    for (int ri = 0; ri < registryCount; ri++) {
                        if (registry[ri].id == a && registry[ri].hasPos) {
                            fixed = true;
                            break;
                        }
                    }
                    if (fixed && vc < 8) {
                        va[vc] = a;
                        vr[vc] = ranges[j];
                        vc++;
                    }
                }
            }

            if (vc >= 3) {
                float sx, sy;
                if (solveTrilateration2D(vr[0], vr[1], vr[2],
                                         va[0], va[1], va[2],
                                         sx, sy)) {
                    SERIAL_LOG.print(F("[SOL] tid="));
                    SERIAL_LOG.print(tid);
                    SERIAL_LOG.print(F(" x="));
                    SERIAL_LOG.print(sx, 2);
                    SERIAL_LOG.print(F(" y="));
                    SERIAL_LOG.println(sy, 2);

                    char solPkt[64];
                    snprintf(solPkt, sizeof(solPkt), "SOL,%d,%.2f,%.2f", tid, sx, sy);
                    udp.beginPacket(IPAddress(255, 255, 255, 255), WIFI_PORT);
                    udp.write((const uint8_t*)solPkt, strlen(solPkt));
                    udp.endPacket();

                    // Also echo over serial so a PC connected via USB can read it
                    SERIAL_LOG.println(solPkt);
                }
            }
        }
        // ------------------------------------------------------------------

        return;
    }

    // ---------- POS: position fix (ANL only) ----------
    if (systemRole == 1 && len >= 4 && strncmp(buf, "POS,", 4) == 0) {
        char* p = buf + 4;
        char* tok1 = strtok(p, ",");
        char* tok2 = strtok(NULL, ",");
        char* tok3 = strtok(NULL, ",");

        if (!tok1 || !tok2) {
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ERR,args");
            udp.endPacket();
            return;
        }

        IPAddress targetIp = remoteIp;
        float x = 0;
        float y = 0;

        if (strchr(tok1, '.')) {
            if (!tok3 || !targetIp.fromString(tok1)) {
                udp.beginPacket(remoteIp, remotePort);
                udp.print("ERR,ip");
                udp.endPacket();
                return;
            }
            x = atof(tok2);
            y = atof(tok3);
        } else {
            x = atof(tok1);
            y = atof(tok2);
        }

        setNodePosition(targetIp, x, y);

        display.fillRect(0, 48, 128, 16, SSD1306_BLACK);
        display.setCursor(0, 50);
        display.print(F("POS OK x="));
        display.print((int)x);
        display.display();

        udp.beginPacket(remoteIp, remotePort);
        udp.print("ACK,POS_OK,");
        udp.print(x, 2);
        udp.print(",");
        udp.println(y, 2);
        udp.endPacket();
        return;
    }

       // ---------- HB: heartbeat (ANL only) ----------
    if (systemRole == 1 && len >= 3 && strncmp(buf, "HB,", 3) == 0) {
        char* p = buf + 3;
        char* idTok = strtok(p, ",");
        char* roleTok = strtok(NULL, ",");
        uint8_t nodeId = 255;
        uint8_t nodeRole = 1;   // default anchor if missing
        if (idTok) nodeId = (uint8_t)atoi(idTok);
        if (roleTok) nodeRole = (uint8_t)atoi(roleTok);

        registerNode(remoteIp, nodeId, nodeRole);
        udp.beginPacket(remoteIp, remotePort);
        udp.print("ACK,HB,");
        udp.println(uwbIndex);
        udp.endPacket();
        return;
    }

    // ---------- ROLE command (node only) ----------
    if (systemRole == 0 && len >= 5 && strncmp(buf, "ROLE,", 5) == 0) {
        int newRole = atoi(buf + 5);
        if (newRole == 0 || newRole == 1) {
            saveRole((uint8_t)newRole);
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ACK,ROLE,");
            udp.println(newRole);
            udp.endPacket();
            delay(500);
            ESP.restart();
        }
        return;
    }

    // ---------- OTA command (any node) ----------
    if (len >= 4 && strncmp(buf, "OTA,", 4) == 0) {
        const char* pw = buf + 4;
        if (strncmp(pw, "rtlsota12", 9) == 0) {
            otaEnabled = true;
            otaEnableTime = millis();
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ACK,OTA,OK,");
            udp.println(uwbIndex);
            udp.endPacket();
            SERIAL_LOG.println(F("[OTA] Window opened (2 min)"));
            display.clearDisplay();
            display.setTextSize(2);
            display.setTextColor(SSD1306_WHITE);
            display.setCursor(0, 18);
            display.println(F("OTA READY"));
            display.setCursor(0, 42);
            display.setTextSize(1);
            display.println(F("2 min window"));
            display.display();
        } else {
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ERR,OTA,BADPASS");
            udp.endPacket();
        }
        return;
    }

    // ---------- ID command (any node) ----------
    if (len >= 3 && strncmp(buf, "ID,", 3) == 0) {
        int newId = atoi(buf + 3);
        if (newId >= 0 && newId <= 7) {
            saveIndex((uint8_t)newId);
            uwbIndex = (uint8_t)newId;
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ACK,ID,");
            udp.println(newId);
            udp.endPacket();
            SERIAL_LOG.print(F("[ID] Set to "));
            SERIAL_LOG.println(newId);
            display.clearDisplay();
            display.setTextSize(2);
            display.setTextColor(SSD1306_WHITE);
            display.setCursor(0, 18);
            display.print(F("ID="));
            display.println(newId);
            display.setCursor(0, 42);
            display.setTextSize(1);
            display.println(F("Rebooting..."));
            display.display();
            delay(800);
            ESP.restart();
        } else {
            udp.beginPacket(remoteIp, remotePort);
            udp.print("ERR,ID,RANGE");
            udp.endPacket();
        }
        return;
    }

    // ---------- ACK to node (ignored silently) ----------
    if (systemRole == 0 && len >= 4 && strncmp(buf, "ACK,", 4) == 0) {
        return;
    }
}

void setNodePosition(IPAddress from, float x, float y)
{
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].ip == from) {
            registry[i].x = x;
            registry[i].y = y;
            registry[i].hasPos = true;
            SERIAL_LOG.print(F("Node "));
            SERIAL_LOG.print(i);
            SERIAL_LOG.print(F(" position set: "));
            SERIAL_LOG.print(x, 2);
            SERIAL_LOG.print(F(", "));
            SERIAL_LOG.println(y, 2);
            return;
        }
    }
    if (registryCount < MAX_REGISTRY_ENTRIES) {
        registry[registryCount].ip = from;
        registry[registryCount].lastSeen = millis();
        registry[registryCount].x = x;
        registry[registryCount].y = y;
        registry[registryCount].hasPos = true;
        SERIAL_LOG.print(F("Registered node "));
        SERIAL_LOG.print(registryCount);
        SERIAL_LOG.print(F(" and set position: "));
        SERIAL_LOG.print(x, 2);
        SERIAL_LOG.print(F(", "));
        SERIAL_LOG.println(y, 2);
        registryCount++;
    }
}

void registerNode(IPAddress from, uint8_t nodeId, uint8_t nodeRole)
{
    int existingIdx = -1;
    for (int i = 0; i < registryCount; i++) {
        if (registry[i].ip == from) {
            existingIdx = i;
            break;
        }
    }

    if (existingIdx >= 0) {
        registry[existingIdx].lastSeen = millis();
        registry[existingIdx].role = nodeRole;           // <-- update role
        if (nodeId != 255 && registry[existingIdx].id == 255) {
            registry[existingIdx].id = nodeId;
        }
        return;
    }

    if (nodeId != 255) {
        for (int i = 0; i < registryCount; i++) {
            if (registry[i].id == nodeId) {
                registry[i].ip = from;
                registry[i].lastSeen = millis();
                registry[i].role = nodeRole;             // <-- update role
                return;
            }
        }
    }

    if (registryCount < MAX_REGISTRY_ENTRIES) {
        registry[registryCount].ip = from;
        registry[registryCount].lastSeen = millis();
        registry[registryCount].id = nodeId;
        registry[registryCount].role = nodeRole;         // <-- set role
        registryCount++;
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
                if (networkId > 9999) networkId = 1000;
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
                    while (digitalRead(BUTTON_PIN) == LOW) delay(10);
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
        SERIAL_LOG.print(F("Current Role: "));
        if (currentRole == 0) {
            SERIAL_LOG.println(F("TAG (0)"));
        } else {
            SERIAL_LOG.println(F("ANCHOR (1)"));
        }
        return;
    }

    if (command.startsWith("AT+ROLE=")) {
        String valueStr = command.substring(8);
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
    if (systemRole == 1) return;

    unsigned long now = millis();
    if (now - lastWifiCheckTime < WIFI_CHECK_INTERVAL) return;
    lastWifiCheckTime = now;

    bool isConnected = (WiFi.status() == WL_CONNECTED);

    if (isConnected && !wifiWasConnected) {
        SERIAL_LOG.println(F("[WiFi] RECONNECTED!"));
        SERIAL_LOG.print(F("IP: "));
        SERIAL_LOG.println(WiFi.localIP());
        wifiWasConnected = true;
        wifiLostTime = 0;
    } else if (!isConnected && wifiWasConnected) {
        SERIAL_LOG.println(F("[WiFi] CONNECTION LOST - Starting reconnect..."));
        wifiWasConnected = false;
        wifiLostTime = now;
        String ssid = ssidForNetId(networkId);
        WiFi.begin(ssid.c_str(), WIFI_PASSWORD);
    } else if (!isConnected && !wifiWasConnected) {
        unsigned long downtime = now - wifiLostTime;
        if (downtime > WIFI_RECONNECT_TIMEOUT) {
            SERIAL_LOG.print(F("[WiFi] Still disconnected after "));
            SERIAL_LOG.print(WIFI_RECONNECT_TIMEOUT / 1000);
            SERIAL_LOG.println(F("s - retrying..."));
            String ssid = ssidForNetId(networkId);
            WiFi.disconnect();
            delay(100);
            WiFi.begin(ssid.c_str(), WIFI_PASSWORD);
            wifiLostTime = now;
        }
    }
}

void updateWifiStatusDisplay()
{
    static unsigned long lastDisplayUpdate = 0;
    static bool lastDisplayedConnected = false;

    if (millis() - lastDisplayUpdate < 2000) return;
    lastDisplayUpdate = millis();

    bool isConnected = (systemRole == 1 || WiFi.status() == WL_CONNECTED);
    if (isConnected == lastDisplayedConnected) return;
    lastDisplayedConnected = isConnected;

    display.fillRect(0, 48, 128, 16, SSD1306_BLACK);
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
}

void drawAnlDashboard()
{
    static unsigned long lastDashboardUpdate = 0;
    static int lastDisplayedCount = -1;
    static int lastDisplayedFixed = -1;

    if (systemRole == 1 && registryCount > 0) {
        registry[0].lastSeen = millis();
    }

    if (millis() - lastDashboardUpdate < 2000) return;
    lastDashboardUpdate = millis();

    int activeNodes = 0;
    int fixedCount = 0;
    unsigned long now = millis();
    for (int i = 0; i < registryCount; i++) {
        unsigned long age = now - registry[i].lastSeen;
        if (age < NODE_TIMEOUT_MS) activeNodes++;
        if (registry[i].hasPos) fixedCount++;
    }

    if (activeNodes == lastDisplayedCount && fixedCount == lastDisplayedFixed) return;
    lastDisplayedCount = activeNodes;
    lastDisplayedFixed = fixedCount;

    display.fillRect(0, 48, 128, 16, SSD1306_BLACK);
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 50);

    display.print(F("ANL C:"));
    display.print(activeNodes);
    display.print(F(" F:"));
    display.print(fixedCount);
    display.print(F("/"));
    display.println(registryCount);

    display.display();
    SERIAL_LOG.print(F("[ANL Dashboard] Active nodes: "));
    SERIAL_LOG.print(activeNodes);
    SERIAL_LOG.print(F(" | Fixed: "));
    SERIAL_LOG.println(fixedCount);
}

void printRegistryTable()
{
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint < 5000) return;
    lastPrint = millis();
    if (systemRole != 1) return;

    SERIAL_LOG.println(F("\n========== ANL REGISTRY =========="));
    unsigned long now = millis();
    for (int i = 0; i < registryCount; i++) {
        unsigned long age = now - registry[i].lastSeen;
        SERIAL_LOG.print(F("Node "));
        SERIAL_LOG.print(i);
        SERIAL_LOG.print(F(" | ID:"));
        SERIAL_LOG.print(registry[i].id);
        SERIAL_LOG.print(F(" | IP: "));
        SERIAL_LOG.print(registry[i].ip);
        SERIAL_LOG.print(F(" | Age(ms): "));
        SERIAL_LOG.print(age);
        if (registry[i].hasPos) {
            SERIAL_LOG.print(F(" | Pos: "));
            SERIAL_LOG.print(registry[i].x, 2);
            SERIAL_LOG.print(F(","));
            SERIAL_LOG.print(registry[i].y, 2);
        } else {
            SERIAL_LOG.print(F(" | Pos: unset"));
        }
        SERIAL_LOG.println(age < NODE_TIMEOUT_MS ? F(" [OK]") : F(" [STALE]"));
    }
    SERIAL_LOG.println(F("=================================="));
}