/*
For ESP32S3 UWB AT Demo

Use 2.0.0    Wire
Use 1.11.7   Adafruit_GFX_Library
Use 1.14.4   Adafruit_BusIO
Use 2.0.0    SPI
Use 2.5.7    Adafruit_SSD1306
*/

// User config  ------------------------------------------

#define UWB_INDEX 0

#define ANCHOR

#define UWB_TAG_COUNT 5
// Define the built-in BOOT button pin
#define BUTTON_PIN 0

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

// --- Function Prototypes ---
void logoshow();
String sendData(String command, const int timeout, boolean debug);
String config_cmd();
String cap_cmd();
// --------------------------------------------

// Variables for debounce (so one press doesn't count as 50)
unsigned long lastDebounceTime = 0;  
unsigned long debounceDelay = 200;    
bool reportingState = true; // Keep track of whether the firehose is ON or OFF


void setup()
{
    pinMode(RESET, OUTPUT);
    digitalWrite(RESET, HIGH);

    SERIAL_LOG.begin(115200);

    SERIAL_LOG.println(F("Hello! ESP32-S3 AT command V1.0 Test"));
    SERIAL_AT.begin(115200, SERIAL_8N1, IO_RXD2, IO_TXD2);

    // EXPLICIT \r\n added here, changed to .print()
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

    logoshow();

    sendData("AT?", 2000, 1);
    // sendData("AT+RESTORE", 5000, 1); // Commented out to preserve settings

    sendData(config_cmd(), 2000, 1);
    sendData(cap_cmd(), 2000, 1);
    
    sendData("AT+SETRPT=1", 2000, 1);
    sendData("AT+SAVE", 2000, 1);
    sendData("AT+RESTART", 2000, 1);

    // Set up the BOOT button with the internal pull-up resistor
    pinMode(BUTTON_PIN, INPUT_PULLUP); 

    SERIAL_LOG.println(F("===================================="));
    SERIAL_LOG.println(F(" PRESS THE 'BOOT' BUTTON TO TOGGLE! "));
    SERIAL_LOG.println(F("===================================="));
}

long int runtime = 0;

String response = "";

void loop()
{
    // 1. Check the physical BOOT button
    if (digitalRead(BUTTON_PIN) == LOW) {
        
        // Debounce: Only trigger if enough time has passed
        if ((millis() - lastDebounceTime) > debounceDelay) {
            
            // Toggle the state
            reportingState = !reportingState; 
            
            if (reportingState == false) {
                SERIAL_LOG.println(F("\n--- BUTTON PRESSED: TURNING OFF ---"));
                // EXPLICIT \r\n added here, changed to .print()
                SERIAL_AT.print("AT+SETRPT=0\r\n");
            } else {
                SERIAL_LOG.println(F("\n--- BUTTON PRESSED: TURNING ON ---"));
                // EXPLICIT \r\n added here, changed to .print()
                SERIAL_AT.print("AT+SETRPT=1\r\n");
            }
            
            lastDebounceTime = millis(); // Reset the debounce timer
        }
    }

    // 2. Normal Keyboard Passthrough
    while (SERIAL_LOG.available() > 0)
    {
        SERIAL_AT.write(SERIAL_LOG.read());
        yield();
    }
    
    // 3. Print the UWB data to the screen
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
    temp = temp + ",1";
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