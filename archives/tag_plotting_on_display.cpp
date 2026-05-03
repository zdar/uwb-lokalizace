/*
For ESP32S3 UWB AT Demo


Use 2.0.0   Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0   SPI
Use 2.5.7   Adafruit_SSD1306

*/

// User config          ------------------------------------------

#define UWB_INDEX 0

#define TAG

#define UWB_TAG_COUNT 5

// User config end       ------------------------------------------

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>

#define SERIAL_LOG Serial
#define SERIAL_AT mySerial2

HardwareSerial SERIAL_AT(2);

#define RESET 16

#define IO_RXD2 18
#define IO_TXD2 17

#define I2C_SDA 39
#define I2C_SCL 38

Adafruit_SSD1306 display(128, 64, &Wire, -1);

// --- Add these "Function Prototypes" here ---
void logoshow();
String sendData(String command, const int timeout, boolean debug);
String config_cmd();
String cap_cmd();
void processResponse(const String &line);
bool parseRangeLine(const String &line, float &distance, String &unit);
void displayRange(float distance, const String &unit);
String formatDistance(float distance, const String &unit);
// --------------------------------------------

float lastDistance = NAN;
unsigned long lastDisplayUpdate = 0;
const unsigned long displayUpdateInterval = 250;

void setup()
{
    pinMode(RESET, OUTPUT);
    digitalWrite(RESET, HIGH);

    SERIAL_LOG.begin(115200);

    SERIAL_LOG.print(F("Hello! ESP32-S3 AT command V1.0 Test"));
    SERIAL_AT.begin(115200, SERIAL_8N1, IO_RXD2, IO_TXD2);

    SERIAL_AT.println("AT");
    Wire.begin(I2C_SDA, I2C_SCL);
    delay(1000);
    // SSD1306_SWITCHCAPVCC = generate display voltage from 3.3V internally
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
    { // Address 0x3C for 128x32
        SERIAL_LOG.println(F("SSD1306 allocation failed"));
        for (;;)
            ; // Don't proceed, loop forever
    }
    display.clearDisplay();

    logoshow();

    sendData("AT?", 2000, 1);
    sendData("AT+RESTORE", 5000, 1);

    sendData(config_cmd(), 2000, 1);
    sendData(cap_cmd(), 2000, 1);

    sendData("AT+SETRPT=1", 2000, 1);
    sendData("AT+SAVE", 2000, 1);
    sendData("AT+RESTART", 2000, 1);
//    sendData("AT+SLEEP=65535", 2000, 1);
//    esp_deep_sleep_start();
}

long int runtime = 0;

String response = "";
String rec_head = "AT+RANGE";

void loop()
{

    // put your main code here, to run repeatedly:
    while (SERIAL_LOG.available() > 0)
    {
        SERIAL_AT.write(SERIAL_LOG.read());
        yield();
    }
    while (SERIAL_AT.available() > 0)
    {
        char c = SERIAL_AT.read();

        if (c == '\r')
            continue;
        else if (c == '\n')
        {
            if (response.length() > 0)
            {
                processResponse(response);
                response = "";
            }
        }
        else
            response += c;
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

    display.setCursor(0, 20); // Start at top-left corner
    // display.println(F("with STM32 AT Command"));

    display.setTextSize(2);

    String temp = "";

    temp = temp + "T" + UWB_INDEX;
    temp = temp + "   6.8M";

    display.println(temp);

    display.setCursor(0, 40);

    temp = "Total: ";
    temp = temp + UWB_TAG_COUNT;
    display.println(temp);

    display.display();

    delay(2000);
}

void processResponse(const String &line)
{
    SERIAL_LOG.println(line);

    float distance;
    String unit;
    if (parseRangeLine(line, distance, unit))
    {
        unsigned long now = millis();
        if (now - lastDisplayUpdate >= displayUpdateInterval || lastDistance != distance)
        {
            lastDistance = distance;
            lastDisplayUpdate = now;
            displayRange(distance, unit);
        }
    }
}

bool parseRangeLine(const String &line, float &distance, String &unit)
{
    String lower = line;
    lower.toLowerCase();

    int rangePos = lower.indexOf("range:");
    if (rangePos >= 0)
    {
        int open = lower.indexOf('(', rangePos);
        int close = lower.indexOf(')', open + 1);
        if (open >= 0 && close > open)
        {
            String tuple = lower.substring(open + 1, close);
            int comma = tuple.indexOf(',');
            if (comma < 0)
                comma = tuple.length();

            String value = tuple.substring(0, comma);
            value.trim();
            if (value.length() > 0 && value != "-1")
            {
                distance = value.toFloat();
                if (distance <= 0.0f)
                    return false;

                // Most DW3000 AT range reports use centimeters.
                // Display as cm for short ranges, switch to meters when useful.
                if (distance >= 100.0f)
                {
                    distance = distance / 100.0f;
                    unit = "m";
                }
                else
                {
                    unit = "cm";
                }
                return true;
            }
        }
    }

    String upper = line;
    upper.toUpperCase();

    // Ignore plain command echo lines.
    if (upper.startsWith("AT+") && upper.indexOf('=') < 0 && upper.indexOf(' ') < 0)
        return false;

    int len = line.length();
    int start = 0;
    while (start < len && !isDigit(line[start]) && line[start] != '.' && line[start] != '-')
        start++;
    if (start >= len)
        return false;

    int pos = start;
    bool seenDot = false;
    if (line[pos] == '-')
        pos++;
    for (; pos < len; pos++)
    {
        char c = line[pos];
        if (isDigit(c))
            continue;
        if (c == '.' && !seenDot)
        {
            seenDot = true;
            continue;
        }
        break;
    }

    String numberString = line.substring(start, pos);
    if (numberString.length() == 0)
        return false;

    distance = numberString.toFloat();
    if (distance == 0 && numberString != "0" && numberString != "0.0")
        return false;

    // Detect units if present
    int unitPos = upper.indexOf("MM", pos);
    if (unitPos < 0)
        unitPos = upper.indexOf("M", pos);
    if (unitPos >= 0)
    {
        String found = upper.substring(unitPos, unitPos + 2);
        if (found == "MM")
            unit = "mm";
        else
            unit = "m";
    }
    else
    {
        // Default guess: values > 1000 are likely millimeters.
        unit = (distance >= 1000.0f) ? "mm" : "m";
    }

    if (unit == "mm" && distance >= 1000.0f)
    {
        distance = distance / 1000.0f;
        unit = "m";
    }

    return true;
}

void displayRange(float distance, const String &unit)
{
    display.clearDisplay();

    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.print(F("MaUWB DW3000"));
    display.setCursor(0, 10);
    display.print(F("Tag "));
    display.print(UWB_INDEX);
    display.print(F("  "));
    display.print(UWB_TAG_COUNT);
    display.print(F(" tags"));

    display.setTextSize(3);
    display.setCursor(0, 24);
    display.print(formatDistance(distance, unit));

    display.setTextSize(1);
    display.setCursor(0, 54);
    display.print(F("Updated"));
    display.drawFastHLine(0, 52, 128, SSD1306_WHITE);

    display.display();
}

String formatDistance(float distance, const String &unit)
{
    if (unit == "cm")
    {
        int value = (int)round(distance);
        return String(value) + " cm";
    }

    if (unit == "mm")
    {
        int value = (int)round(distance);
        return String(value) + " mm";
    }

    return String(distance, 2) + " m";
}

String sendData(String command, const int timeout, boolean debug)
{
    String response = "";
    // command = command + "\r\n";

    SERIAL_LOG.println(command);
    SERIAL_AT.println(command); // send the read character to the SERIAL_LOG

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
        SERIAL_LOG.println(response);
    }

    return response;
}

String config_cmd()
{
    String temp = "AT+SETCFG=";

    // Set device id
    temp = temp + UWB_INDEX;

    // Set device role
    //x2:Device Role(0:Tag / 1:Anchor)
    temp = temp + ",0";

    // Set frequence 850k or 6.8M

    temp = temp + ",1";

    // Set range filter
    temp = temp + ",1";

    return temp;
}

String cap_cmd()
{
    String temp = "AT+SETCAP=";

    // Set Tag capacity
    temp = temp + UWB_TAG_COUNT;

    //  Time of a single time slot  6.5M : 10MS  850K ： 15MS
    temp = temp + ",10";
    
    //X3:extMode, whether to increase the passthrough command when transmitting
    //(0: normal packet when communicating, 1: extended packet when communicating)
    temp = temp + ",1";
    
    return temp;
}
