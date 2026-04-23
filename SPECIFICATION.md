 ## 1. Overview
 
 ### 1.1 Final System Constraints
 1. **Homogeneous Hardware:** All devices are identical MAUWBS3CA1 modules [1]
 2. **Battery-Only Operation:** No wired power assumed for any device
 3. **Optional IMU:** 9DOF sensor is optional. All TAGs must have it. Anchors may or may not.
 4. **Role Selection:** Role (ANCHOR/TAG/ANL) selected at startup from persistent config
 5. **Any-Device ANL:** Network coordinator can be any device (Anchor or TAG)
 6. **TAG-Centric Compute:** Only TAG roles perform EKF localization
 7. **Manual ANL Forcing:** Specific device can be forced to be ANL
 8. **Unified Firmware:** Single firmware image for all devices/roles
 9. **Mandatory OLED:** SSD1306 display for local UI on all devices
 
 ### 1.2 System Characteristics
 - **Localization Method:** UWB Time-of-Flight (TWR) two-sided distance measurement [1]
 - **Position Accuracy:** &lt;10 cm under optimal conditions [1]
 - **RF Band:** CH5 (6489.6 MHz) [1]
 - **Data Rates:** 850 kbps and 6.8 Mbps [1]
 - **Maximum Packet Length:** 1023 bytes [1]
 - **Anchor Capacity:** Unlimited (from firmware v1.1.3) [1]
 - **Tag Capacity:** Maximum 64 tags [1]
 - **Refresh Rate:** Configurable up to 100 Hz [1]
 - **Battery:** 2000mAh LiPo (all devices)
 - **Sleep Current:** 35 µA (Tag deep hibernation) [1]
 - **Working Current:** 34 mA [1]
 
 ---
 
 ## 2. Hardware Platform
 
 ### 2.1 MAUWBS3CA1 Module Technical Specifications [1]
 
 | Component | Specification | Notes |
 |-----------|---------------|-------|
 | **MCU** | ESP32-S3 Dual-core 240 MHz | |
 | **UWB Chip** | Qorvo DW3000 series | IEEE 802.15.4-2011 compliant [1] |
 | **RF Band** | CH5 (6489.6 MHz) [1] | |
 | **Data Rates** | 850 kbps and 6.8 Mbps [1] | |
 | **Max Packet Length** | 1023 bytes [1] | |
 | **Serial Baud Rate** | 115200 bps [1] | |
 | **Sleep Current** | 35 µA (Tag deep hibernation) [1] | |
 | **Working Current** | 34 mA [1] | |
 | **IMU** | 9DOF (MPU-9250 or equivalent) | Optional |
 | **OLED Display** | SSD1306 128×64 I²C | Mandatory for all devices |
 | **Memory** | 8MB Flash, 8MB PSRAM | |
 | **Power** | 3.3V ±5% (strict requirement) [1] | Exceeding damages module [1] |
 
 ### 2.2 Pin Definition [1]
 
 | Pin | Name | Function | Role Usage |
 |-----|------|----------|------------|
 | 1,2 | 3V3 | Power 3.3V | All devices - **Critical:** 3.3V ±5% only [1] |
 | 3 | I2CSDA | Reserved pin | Used for OLED display (I²C) |
 | 4 | I2CSCL | Reserved pin | Used for OLED display (I²C) |
 | 5 | SWCLK | Module download port | Firmware upgrades |
 | 6 | SWDIO | Module download port | Firmware upgrades |
 | 7,8,16 | GND | Ground | All devices |
 | 9 | RUN LED | Module running indicator | Universal (except Tag in sleep) [1] |
 | 10 | UART2 TX | Reserved pin | Not used |
 | 11 | UART2 RX/RESET/WAKEUP | Multi-function pin | 3s pull-down = reset; Tag sleep = wake-up [1] |
 | 12 | TX LED | UWB transmit indicator | **Anchor only** [1] |
 | 13 | RX LED | UWB acceptance indicator | **Anchor only** [1] |
 | 14 | UART1 TX | Module serial TX port | Main UART for AT commands [1] |
 | 15 | UART1 RX | Module serial RX port | Main UART for AT commands [1] |
 
 ### 2.3 LED Indicators [1]
 
 - **RUN LED (Pin 9):** Universal for Anchor/Tag (except Tag in sleep)
   - Configuration status: Blinking slowly (1 second interval)
   - Working status: Blinking at short intervals (0.1 seconds)
 
 - **TX LED (Pin 12):** UWB transmit indicator (**Anchor only**)
 - **RX LED (Pin 13):** UWB acceptance indicator (**Anchor only**)
 
 ### 2.4 Power Requirements [1]
 - **Voltage:** 3.3V ±5% (**strict** - exceeding damages module) [1]
 - **Current:** Working: 34 mA, Tag deep sleep: 35 µA [1]
 - **Regulation:** LDO voltage regulator with 100µF tantalum + 100nF capacitor recommended [1]
 
 ### 2.5 Physical Dimensions [1]
 - **Module size:** 30mm × 21mm
 - **Height:** 3mm (board), 2.2mm (components), 1.1mm (antenna area)
 
 ---
 
 ## 3. AT Command System Integration [1]
 
 ### 3.1 Command Architecture
 All UWB communication uses AT commands via UART1 at 115200 bps [1].
 
 ### 3.2 Essential Command Sequence
 
 #### Initialization (All Devices):
 ```shell
 AT?                     # Verify serial communication [1]
 AT+GETVER?              # Get software/hardware version [1]
 AT+SETCFG=(id),(role),(rate),(filter)  # Configure device [1]
 AT+SETCAP=(tag_capacity),(slot_time),(extMode)  # Set system capacity [1]
 AT+SETPAN=(network_id)  # Set network ID [1]
 AT+SAVE                 # Save to flash [1]
 AT+SETRPT=1             # Enable auto-reporting [1]
 ```
 
 #### Critical Parameters:
 - **Device ID:** Anchor: 0-unlimited, Tag: 0-63 [1]
 - **Device Role:** 0:Tag, 1:Anchor [1]
 - **Communication Rate:** 0:850K, 1:6.8M [1]
 - **Range Filtering:** 0:Close, 1:Open [1]
 - **Multi-zone positioning:** Use 6.8Mbps and close distance filtering [1]
 
 ### 3.3 Range Data Format [1]
 ```
 AT+RANGE=tid:x1,mask:x2,seq:x3,range:(x4-x11),ancid:(x20-x27)
 ```
 - **tid:** Tag ID (decimal)
 - **mask:** Significance bit (hexadecimal)
 - **seq:** Tag communication sequence (decimal)
 - **range0-7:** Distance from Tag to Anchor 0-7 (cm, decimal)
 - **ancid0-7:** Device ID of Anchor 0-7
 - **Note:** Tags automatically select 8 nearest Anchors from unlimited pool [1]
 
 ### 3.4 Refresh Rate Configuration [1]
 ```
 Refresh Rate (Hz) = 1 / (Tag_Capacity × Single_Slot_Time)
 ```
 Examples:
 - 10 tags × 10ms slot = 10 Hz
 - 5 tags × 10ms slot = 20 Hz
 - 1 tag × 10ms slot = 100 Hz
 
 ### 3.5 Sleep Command (Tag Only) [1]
 - `AT+SLEEP=(ms)` - Sleep time 0-65535 ms (65535 = forever) [1]
 - Wake methods: Serial data or UART2 RX pin pull-down [1]
 
 ### 3.6 Network Segregation [1]
 - `AT+SETPAN=(network_id)` - Default: 1111 [1]
 - Only devices with same PAN ID can communicate [1]
 - Enables multiple independent RTLS networks in same space
 
 ---
 
 ## 4. System Architecture
 
 ### 4.1 Device Roles &amp; Capabilities
 
 | Role | Required Capabilities | Can be ANL? | Performs EKF? | OLED Display |
 |------|----------------------|-------------|---------------|--------------|
 | **ANCHOR** | UWB, WiFi, BLE | YES | NO | Yes (status) |
 | **FOLLOWER_TAG** | UWB, WiFi, BLE, **IMU** | NO | YES (local) | Yes (position) |
 | **HOT_STANDBY_TAG** | UWB, WiFi, BLE, **IMU** | YES | YES (mirror) | Yes (status) |
 | **ANL (Anchor)** | UWB, WiFi, BLE | (is ANL) | NO | Yes (network) |
 | **ANL (TAG)** | UWB, WiFi, BLE, **IMU** | (is ANL) | YES (central) | Yes (full) |
 
 ### 4.2 Network Topology
 
 #### Preferred: ANL is a TAG
 ```
 [ANL-TAG] (WiFi AP + EKF + OLED)
     │
     ├── [Anchor1] (OLED: status) ──┐
     ├── [Anchor2] (OLED: status) ──┤ → UWB Ranging
     └── [Anchor3] (OLED: status) ──┘
     │
     ├── [Follower TAG1] (OLED: position)
     └── [Follower TAG2] (OLED: position)
 ```
 
 #### Alternative: ANL is an Anchor (Split Compute)
 ```
 [ANL-Anchor] (WiFi AP + OLED: network)
     │
     ├── [EKF-TAG*] (OLED: compute status) ← Designated compute node
     │   │
     │   ├── [Anchor1] (OLED: status)
     │   ├── [Anchor2] (OLED: status) → UWB Ranging
     │   └── [Anchor3] (OLED: status)
     │
     └── [Follower TAGs] (OLED: position)
 ```
 
 ### 4.3 OLED Display Content
 
 #### All Devices (Common):
 - Device Role &amp; ID
 - Battery Level
 - Network Status (PAN ID) [1]
 - RUN LED status indicator [1]
 
 #### Role-Specific:
 - **Anchor:** UWB status, connected tags count
 - **Tag:** Distance to nearest anchor, position coordinates
 - **ANL:** Network topology, device count, system health
 - **Hot Standby:** ANL heartbeat status, promotion readiness
 
 ### 4.4 Battery-Aware Leader Election
 
 #### Election Scoring:
 ```
 Score = (Battery_Capacity × 0.4)
       + (Uptime_Stability × 0.2)
       + (Anchor_Connectivity × 0.2)
       + (External_Connectivity × 0.2)
 ```
 
 #### ANL Eligibility:
 1. Battery ≥ 15%
 2. WiFi AP capable (all devices)
 3. If `has_imu = false` (Anchor as ANL), must designate EKF-TAG
 4. Manual force overrides all rules
 
 ### 4.5 Manual ANL Forcing
 
 #### Force Mechanisms:
 1. **Physical Button:** 5s hold + click sequence
 2. **Web UI:** Admin interface
 3. **BLE:** Mobile app command
 4. **OLED Interface:** Menu-driven option
 
 #### Force State Machine:
 ```
 AUTO_ELECTION → ANL_FORCED_PENDING → ANL_FORCED_ACTIVE
        ↑                                       ↓
        └─────── CLEAR/DEMOTE/FAILURE ←───────┘
 ```
 
 #### Safety Features:
 - Auto-expiry: 72 hours default
 - Low-battery override: &lt;5% battery forces clear
 - Failure fallback: Auto-election resumes
 - OLED indication: &quot;ANL (Forced)&quot; with expiry timer
 
 ---
 
 ## 5. Power Management
 
 ### 5.1 Universal Battery Operation
 - All devices: 2000mAh LiPo
 - Charging: USB-C or wireless charging
 - Power monitoring: Every 1% change or 5 minutes
 
 ### 5.2 AT Command Power Control [1]
 - Sleep: `AT+SLEEP=(ms)` for Tags [1]
 - Transmission Power: `AT+SETPOW=(gain)` [1]
 - Default power gain: FD (hex) [1]
 
 ### 5.3 Role-Specific Power Profiles
 
 | Role | Performance | Balanced | Power Saver |
 |------|-------------|----------|-------------|
 | **ANL** | 3 hours | 8 hours | 24 hours |
 | **Hot Standby** | 4 hours | 10 hours | 48 hours |
 | **Follower TAG** | 5 hours | 12 hours | 60 hours |
 | **Anchor** | 8 hours | 24 hours | 7 days |
 
 ### 5.4 OLED Power Management
 - Brightness adjustable based on ambient light
 - Auto-off after 30 seconds inactivity
 - Critical alerts override auto-off
 - Low-power mode reduces refresh rate
 
 ---
 
 ## 6. Firmware Architecture
 
 ### 6.1 Module Structure
 ```
 firmware/
 ├── main/                    # Application entry
 ├── components/
 │   ├── uwb_at_interface/    # AT command layer [1]
 │   ├── oled_display/        # SSD1306 driver
 │   ├── role_manager/        # Role selection &amp; ANL forcing
 │   ├── imu_fusion/          # Adaptive yaw (if has_imu)
 │   ├── ekf_engine/          # TAG-only EKF
 │   ├── wifi_manager/        # Duty-cycled AP
 │   ├── power_manager/       # Battery-aware operation
 │   ├── ble_stack/           # Provisioning
 │   └── network_orchestrator/# Registry, discovery
 └── partitions/             # Dual OTA layout
 ```
 
 ### 6.2 AT Command Integration Layer
 ```cpp
 class UWBInterface {
 public:
     void init(bool asAnchor, uint8_t id, uint8_t rate) {
         // Send AT commands based on role [1]
         if (asAnchor) {
             sendCommand(&quot;AT+SETCFG=%d,1,%d,0&quot;, id, rate);  // Anchor [1]
         } else {
             sendCommand(&quot;AT+SETCFG=%d,0,%d,0&quot;, id, rate);  // Tag [1]
         }
         sendCommand(&quot;AT+SETCAP=10,10,0&quot;);  // 10 tags, 10ms slot [1]
         sendCommand(&quot;AT+SAVE&quot;);            // Save to flash [1]
     }
     
     RangeData getRanges() {
         // Parse: AT+RANGE=tid:x1,mask:x2,seq:x3,range:(x4-x11),ancid:(x20-x27) [1]
         return parseRangeData(lastResponse);
     }
 };
 ```
 
 ### 6.3 OLED Display Driver
 ```cpp
 class OLEDDisplay {
 public:
     void showDeviceStatus(Role role, uint8_t id, float battery) {
         display.clearDisplay();
         display.setTextSize(1);
         display.setCursor(0,0);
         
         // Show role-specific info
         switch(role) {
             case ROLE_ANCHOR:
                 display.print(&quot;ANCHOR &quot;);
                 display.println(id);
                 display.print(&quot;BATT: &quot;);
                 display.print(battery);
                 display.println(&quot;%&quot;);
                 break;
             case ROLE_TAG:
                 display.print(&quot;TAG &quot;);
                 display.println(id);
                 display.print(&quot;POS: &quot;);
                 display.print(lastPosition.x);
                 display.print(&quot;,&quot;);
                 display.print(lastPosition.y);
                 break;
             // ... additional cases
         }
         display.display();
     }
 };
 ```
 
 ---
 
 ## 7. Deployment Guidelines
 
 ### 7.1 Hardware Setup
 1. **Power:** Apply 3.3V ±5% to pins 1/2 [1]
 2. **Serial:** Connect to UART1 TX/RX (pins 14/15) at 115200 bps [1]
 3. **OLED:** Connect to I2C pins 3/4
 4. **Test:** Send `AT?` → should return `OK` [1]
 
 ### 7.2 Configuration Procedure
 ```shell
 # Step 1: Basic configuration [1]
 AT+SETCFG=0,1,1,0    # ID=0, Anchor, 6.8M, no filter [1]
 AT+SETCAP=10,10,0    # 10 tags, 10ms slot, normal packet [1]
 AT+SETPAN=1234       # Network ID [1]
 AT+SAVE              # Save to flash [1]
 
 # Step 2: Role selection via OLED menu
 # Use device button to select role
 # Role saved to NVS
 
 # Step 3: Network formation
 # ANL creates WiFi network
 # Other devices join automatically
 ```
 
 ### 7.3 Multi-Zone Positioning [1]
 1. Use 6.8Mbps data rate (`AT+SETCFG`, x3=1) [1]
 2. Close distance filtering (`AT+SETCFG`, x4=0) [1]
 3. Deploy unlimited Anchors throughout area [1]
 4. Tags automatically select 8 nearest Anchors [1]
 
 ### 7.4 OLED Calibration
 1. Initial brightness setting
 2. Contrast adjustment for environment
 3. Information hierarchy configuration
 4. Alert priority settings
 
 ---
 
 ## 8. Performance Specifications
 
 ### 8.1 UWB Performance [1]
 - **Standard:** IEEE 802.15.4-2011
 - **Range:** Up to 100m (line-of-sight)
 - **Accuracy:** &lt;10 cm (optimal conditions) [1]
 - **Refresh Rate:** Configurable up to 100 Hz [1]
 - **Anchor Capacity:** Unlimited [1]
 - **Tag Capacity:** 64 maximum [1]
 
 ### 8.2 System Performance
 - **Position Update Rate:** 1-100 Hz (configurable) [1]
 - **ANL Failover Time:** &lt;10 seconds
 - **Network Join Time:** &lt;30 seconds
 - **OLED Refresh Rate:** 10 Hz (configurable)
 - **Battery Life:** 3-24 hours (mode dependent)
 
 ### 8.3 AT Command Performance [1]
 - **Baud Rate:** 115200 bps [1]
 - **Response Time:** &lt;100 ms typical
 - **Flash Write Cycles:** 100,000 minimum
 - **Sleep Wake Time:** &lt;10 ms [1]
 
 ---
 
 ## 9. Troubleshooting
 
 ### 9.1 Common AT Command Issues [1]
 - **No Response:** Verify 3.3V power, 115200 baud, proper TX/RX connection [1]
 - **High Distance Error:** Calibrate antenna delay with `AT+SETANT` [1]
 - **Network Interference:** Change PAN ID via `AT+SETPAN` [1]
 - **Tag Not Sleeping:** Verify `AT+SLEEP` command and wake-up pin configuration [1]
 
 ### 9.2 OLED Issues
 - **No Display:** Check I2C connection (pins 3/4)
 - **Flickering:** Power supply instability
 - **Wrong Content:** Firmware mismatch or configuration error
 
 ### 9.3 LED Status Diagnosis [1]
 - **RUN LED not blinking:** Power issue or module fault
 - **RUN LED slow blink (1s):** Configuration mode
 - **RUN LED fast blink (0.1s):** Normal operation
 - **TX/RX LEDs inactive on Tag:** Normal (Anchor only) [1]
 
 ---
 
 ## 10. Appendices
 
 ### 10.1 AT Command Quick Reference [1]
 
 #### Device Configuration:
 ```
 AT+SETCFG=(id),(role:0=Tag/1=Anchor),(rate:0=850K/1=6.8M),(filter:0=Off/1=On) [1]
 AT+SETCAP=(tag_capacity:1-64),(slot_time_ms),(extMode:0/1) [1]
 AT+SETPAN=(network_id) [1]
 AT+SAVE [1]
 ```
 
 #### Operation:
 ```
 AT+SETRPT=1  # Enable auto-reporting [1]
 AT+RANGE     # Returns distance data [1]
 AT+SLEEP=(ms) # Tag sleep [1]
 ```
 
 #### Information:
 ```
 AT?          # Serial test [1]
 AT+GETVER?   # Get version [1]
 AT+GETCFG?   # Get configuration [1]
 AT+GETPAN?   # Get network ID [1]
 ```
 
 ### 10.2 Default Values [1]
 | Parameter | Default | Command |
 |-----------|---------|---------|
 | Device Role | Not set (-1) | AT+GETCFG? [1] |
 | Communication Rate | 6.8M (1) | AT+GETCFG? [1] |
 | Range Filtering | Open (1) | AT+GETCFG? [1] |
 | Antenna Delay | 16336 | AT+GETANT? [1] |
 | Tag Capacity | 10 | AT+GETCAP? [1] |
 | Slot Time | 10ms | AT+GETCAP? [1] |
 | Auto-report | On (1) | AT+GETRPT? [1] |
 | Transmit Power | FD (hex) | AT+GETPOW? [1] |
 | PAN ID | 1111 | AT+GETPAN? [1] |
 
 ### 10.3 Safety Warnings [1]
 1. **Voltage:** Do not exceed 3.3V ±5% - will damage module [1]
 2. **ESD:** Handle with anti-static precautions
 3. **RF Exposure:** Install per local regulations
 4. **Battery:** Use only specified 2000mAh LiPo
 
 ### 10.4 Revision History
 | Version | Date | Changes |
 |---------|------|---------|
 | 3.1 | 2024-05-15 | Integrated AT command details from manual [1] |
 | 3.0 | 2024-05-15 | Complete spec with manual ANL forcing |
 | 2.3 | 2024-05-15 | IMU optional, any-device ANL |
 | 2.2 | 2024-05-15 | All battery, homogeneous hardware |
 | 2.1 | 2024-05-15 | Unified UI, multi-uplink |
 
 ---
 
 **Based on:** Makerfabs UWB AT Module AT Command Manual(v1.1.2).pdf [1]  
 
 **Note:** This specification integrates the official AT command manual [1] with the complete RTLS system design including OLED display, unified firmware, role selection, and network architecture discussed in previous conversations.
 ```
 
