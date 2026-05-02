/*
For ESP32S3 UWB AT Demo


Use 2.0.0   Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0   SPI
Use 2.5.7   Adafruit_SSD1306

*/

//去掉DTR脚串口， 否则一直拉低复位脚

// User config          ------------------------------------------

#define UWB_INDEX 0

#define ANCHOR

#define UWB_TAG_COUNT 64

// User config end       ------------------------------------------

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>

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

// --- Add these "Function Prototypes" here ---
void logoshow();
String sendData(String command, const int timeout, boolean debug);
String config_cmd();
String cap_cmd();
// --------------------------------------------
void setup()
{
    pinMode(RESET, OUTPUT);
    digitalWrite(RESET, HIGH);

    SERIAL_LOG.begin(115200);
    SERIAL_AT.begin(115200, SERIAL_8N1, IO_RXD2, IO_TXD2);

    SERIAL_LOG.println(F("Hello! ESP32-S3 AT command V1.0 Test"));
    
    Wire.begin(I2C_SDA, I2C_SCL);
    delay(1000);
    
    // SSD1306_SWITCHCAPVCC = generate display voltage from 3.3V internally
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C))
    { // Address 0x3C for 128x32
        SERIAL_LOG.println(F("SSD1306 allocation failed"));
        for (;;)
            ; // Don't proceed, loop forever
    }
// ... display code ...
    display.clearDisplay();
    logoshow();

    // =========================================================
    // THE ANTIDOTE: Tell the DW3000 to shut up, and save it!
    // =========================================================
    SERIAL_LOG.println(F("Applying the silence antidote..."));
    sendData("AT+SETRPT=0", 2000, 1); // 0 = Turn OFF auto-reporting
    sendData("AT+SAVE", 2000, 1);     // Save this quiet state!
    
    SERIAL_LOG.println(F("===================================="));
    SERIAL_LOG.println(F("   INTERACTIVE PASSTHROUGH READY    "));
    SERIAL_LOG.println(F("   Type your AT commands below!     "));
    SERIAL_LOG.println(F("===================================="));
}


void loop()
{
    // 1. If you type in VS Code, send it straight to the DW3000
    while (SERIAL_LOG.available() > 0)
    {
        SERIAL_AT.write(SERIAL_LOG.read());
        yield();
    }
    
    // 2. If the DW3000 responds, send it straight to VS Code
    while (SERIAL_AT.available() > 0)
    {
        // Using Serial.write instead of building a string prevents
        // line-ending bugs and shows you exactly what the module outputs
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

    display.setCursor(0, 20); // Start at top-left corner
    // display.println(F("with STM32 AT Command"));

    display.setTextSize(2);

    String temp = "";

    temp = temp + "A" + UWB_INDEX;

    temp = temp + "   6.8M";
    
    display.println(temp);

    display.setCursor(0, 40);

    temp = "Total: ";
    temp = temp + UWB_TAG_COUNT;
    display.println(temp);

    display.display();

    delay(2000);
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
    temp = temp + ",1";


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