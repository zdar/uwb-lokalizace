
// change the setup and loop to this to send manual AT commands to the module, and see the response in the Serial Monitor

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