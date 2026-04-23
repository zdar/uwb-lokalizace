 # Complete RTLS System Specification v4.0
 *Multi-Node Real-Time Location System - Unified Final Specification*
  
 ## Executive Summary
 This document consolidates all solutions from the complete design discussion into a single, implementable specification for a homogeneous, battery-powered RTLS network using MAUWBS3CA1 modules.
 
 ## 1. Core Design Principles (Final)
 
 1. **Unified Hardware:** All devices use identical MAUWBS3CA1 modules
 2. **Mandatory OLED:** SSD1306 display on all devices for local UI
 3. **Battery-Only:** All devices battery-powered (2000mAh LiPo)
 4. **Runtime Role Selection:** Role chosen at boot (Anchor/Tag/ANL/Hot Standby)
 5. **Any-Device ANL:** Any node can be network coordinator
 6. **Manual ANL Forcing:** Specific device can be forced as ANL
 7. **Optional IMU:** 9DOF sensor on Tags only (for position offset)
 8. **Unified Firmware:** Single image with role-based feature enablement
 9. **Multi-Provisioning:** WiFi AP, BLE, and OLED for configuration
 10. **Self-Healing:** Automatic failover with Hot Standby
 
 ## 2. Complete Hardware Specification
 
 ### 2.1 MAUWBS3CA1 Module Configuration
 - **MCU:** ESP32-S3 (handles WiFi, BLE, OLED, system logic)
 - **UWB:** DW3000 via AT commands [1]
 - **OLED:** SSD1306 128×64 via I²C (pins 3-4) [1]
 - **IMU:** MPU-9250 9DOF (Tags only, optional for Anchors)
 - **Battery:** 2000mAh LiPo with charging circuit
 - **Power:** 3.3V ±5% (strict requirement) [1]
 
 ### 2.2 Pin Usage Allocation
 | Pin | Function | Usage in Our System |
 |-----|----------|---------------------|
 | 1-2 | 3V3 Power | Battery via regulator |
 | 3-4 | I2C SDA/SCL | OLED display |
 | 9 | RUN LED | System status indicator [1] |
 | 11 | UART2 RX/RESET | Role selection button + reset |
 | 14-15 | UART1 TX/RX | UWB AT commands [1] |
 | 12-13 | TX/RX LEDs | Debug indicators |
 
 ### 2.3 OLED Display Requirements
 - **Library:** Adafruit_SSD1306
 - **Content:**
   - Device role and ID
   - Battery percentage
   - Network status
   - For Tags: position/distance
   - For ANL: connected devices count
   - Configuration menu for role selection
 
 ## 3. Unified Firmware Architecture
 
 ### 3.1 Boot Sequence
 ```
 Power On
     ↓
 Read NVS for: role, WiFi creds, force_flag
     ↓
 If force_flag == ANL_FORCED → Become ANL immediately
     ↓
 Else if role == UNCONFIGURED → Start provisioning mode
     ↓
 Else → Initialize in configured role
     ↓
 Start OLED with role-specific UI
     ↓
 Join/Create network based on role
 ```
 
 ### 3.2 Role Management
 ```cpp
 typedef enum {
     ROLE_UNCONFIGURED = 0,
     ROLE_ANCHOR,      // UWB only, no IMU
     ROLE_TAG,         // UWB + IMU + position
     ROLE_ANL,         // Network coordinator
     ROLE_HOT_STANDBY  // Failover ready
 } device_role_t;
 
 // Stored in NVS, changeable via OLED menu/BLE/WiFi
 ```
 
 ### 3.3 Module Structure
 ```
 firmware/
 ├── main/                    # Boot and role dispatch
 ├── drivers/
 │   ├── uwb_at.c           # AT command interface [1]
 │   ├── ssd1306_ui.c       # OLED display manager
 │   ├── imu_9dof.c         # TAG-only IMU fusion
 │   └── power_mgr.c        # Battery management
 ├── roles/
 │   ├── anchor.c           # Anchor behavior
 │   ├── tag.c              # TAG behavior (with EKF)
 │   ├── anl.c              # ANL behavior (WiFi AP + registry)
 │   └── hot_standby.c      # Hot Standby behavior
 ├── network/
 │   ├── provisioning.c     # WiFi AP + BLE for setup
 │   ├── registry.c         # Device registry (ANL only)
 │   └── election.c         # ANL election algorithm
 └── services/
     ├── web_ui.c           # Configuration web server
     ├── ble_config.c       # BLE provisioning service
     └── cloud_sync.c       # Optional cloud upload
 ```
 
 ## 4. Provisioning System (WiFi + BLE + OLED)
 
 ### 4.1 Multi-Method Provisioning
 ```
 Unconfigured Device Boot:
 1. OLED shows: &quot;Select provisioning method:&quot;
 2. Options:
    a. OLED Menu (button navigation)
    b. WiFi AP: &quot;RTLS-Config-XXXX&quot;
    c. BLE: &quot;RTLS-Config&quot; service
 3. User chooses method → enters configuration
 ```
 
 ### 4.2 WiFi Provisioning AP
 - **SSID:** `RTLS-Config-&lt;LAST4_MAC`
 - **IP:** 192.168.4.1
 - **Web UI:** Full configuration portal
 - **Timeout:** 30 minutes, then reboots
 - **Security:** WPA2 with generated password
 
 ### 4.3 BLE Provisioning Service
 ```
 Service UUID: 6E40xxxx-B5A3-F393-E0A9-E50E24DCCA9E
 Characteristics:
   - Device Info (read)
   - Network Config (write)
   - Role Selection (write)
   - Status (notify)
 ```
 
 ### 4.4 OLED Configuration Menu
 ```
 Navigate with button (pin 11):
 Short press: Next item
 Long press: Select/Confirm
 
 Menu Structure:
 Main Menu → Role → Anchor/Tag/ANL → Confirm
             → WiFi Config → SSID → Password
             → Network ID → [PAN ID from AT+SETPAN] [1]
             → Force ANL → Enable/Disable
             → Save &amp; Reboot
 ```
 
 ## 5. UWB System Integration [1]
 
 ### 5.1 AT Command Initialization
 ```cpp
 // Common initialization for all devices
 void uwb_init(uint8_t id, bool is_anchor) {
     send_command(&quot;AT+SETCFG=%d,%d,1,0&quot;, id, is_anchor ? 1 : 0); // [1]
     send_command(&quot;AT+SETCAP=10,10,0&quot;);  // 10Hz default [1]
     send_command(&quot;AT+SETPAN=%d&quot;, network_id); // [1]
     send_command(&quot;AT+SAVE&quot;); // [1]
     send_command(&quot;AT+SETRPT=1&quot;); // Enable auto-report [1]
 }
 
 // TAG-specific sleep
 void tag_sleep(uint32_t ms) {
     if (ms  0) send_command(&quot;AT+SLEEP=%lu&quot;, ms); // [1]
 }
 ```
 
 ### 5.2 Range Data Processing
 ```cpp
 // Parse: AT+RANGE=tid:x1,mask:x2,seq:x3,range:(x4-x11),ancid:(x20-x27) [1]
 typedef struct {
     uint8_t tag_id;
     uint8_t mask;
     uint16_t sequence;
     float ranges[8];  // in meters
     int8_t anchor_ids[8];  // -1 if not used
 } range_data_t;
 ```
 
 ### 5.3 Refresh Rate Management
 - **Formula:** `rate_hz = 1 / (tag_capacity × slot_time)` [1]
 - **Dynamic Adjustment:** Based on battery level and network size
 - **ANL Coordinates:** Broadcasts optimal settings to all devices
 
 ## 6. Network Architecture
 
 ### 6.1 ANL (Active Network Leader) Responsibilities
 - Creates WiFi network: `RTLS-Net-&lt;ANL_ID`
 - Maintains device registry
 - Coordinates UWB ranging schedules
 - Handles failover to Hot Standby
 - Optional cloud uplink
 
 ### 6.2 Hot Standby System
 - Mirrors ANL&#x27;s registry
 - Monitors ANL heartbeat (UDP + BLE)
 - Promotes in &lt;10s on failure
 - Maintains dormant external connection
 
 ### 6.3 Battery-Aware Election
 ```
 Election Score = 
   (battery_level × 0.4) +
   (has_imu × 0.1) +      // Prefer TAGs as ANL
   (uptime × 0.2) +
   (signal_strength × 0.3)
 
 Rules:
 1. Battery &lt;15% → cannot be ANL
 2. Manual force overrides all scores
 3. ANL-Anchor must designate EKF-TAG
 ```
 
 ### 6.4 Manual ANL Forcing
 **Methods:**
 1. **OLED Menu:** Device settings → &quot;Force as ANL&quot;
 2. **Web UI:** Admin interface on ANL
 3. **BLE Command:** Mobile app
 4. **Physical Button:** 5-second hold + pattern
 
 **Persistence:** Saved in NVS, survives reboot
 **Safety:** 72-hour auto-expiry, low-battery override
 
 ## 7. Power Management
 
 ### 7.1 Battery Profiles (2000mAh LiPo)
 | Role | Performance | Balanced | Power Saver |
 |------|-------------|----------|-------------|
 | **ANL** | 3 hours | 8 hours | 24 hours |
 | **Tag** | 5 hours | 12 hours | 48 hours |
 | **Anchor** | 8 hours | 24 hours | 7 days |
 
 ### 7.2 Dynamic Power Adjustment
 ```cpp
 void update_power_state() {
     float battery = read_battery();
     
     if (role == ROLE_ANL) {
         if (battery &lt; 0.2) initiate_demotion();
         if (battery &lt; 0.5) set_ap_duty_cycle(0.05); // 5%
         if (battery &lt; 0.8) set_uwb_rate(5); // 5Hz
     }
     
     if (battery &lt; 0.1) {
         deep_sleep(3600); // 1 hour sleep
     }
 }
 ```
 
 ### 7.3 OLED Power Saving
 - Dim after 30 seconds
 - Off after 2 minutes (except for alerts)
 - Wake on button press or alert
 - Minimum refresh rate: 1Hz in low power
 
 ## 8. Position Computation (TAGs Only)
 
 ### 8.1 EKF with IMU Fusion
 ```
 State Vector (TAG):
 [x, y, z, vx, vy, vz, q0, q1, q2, q3, bgx, bgy, bgz]
 
 Offset Correction:
 P_reference = P_antenna + R(quaternion) × offset_vector
 
 Sensor Fusion:
 - UWB ranges: Position updates
 - IMU gyro: Orientation prediction
 - IMU accel: Velocity/position (with drift)
 - Magnetometer: Yaw correction (disturbance-aware)
 ```
 
 ### 8.2 Anchor Processing
 - No position computation
 - UWB ranging only
 - Forward ranges to ANL (or EKF-TAG if ANL is Anchor)
 
 ## 9. Deployment Workflow
 
 ### 9.1 Initial Device Setup
 ```
 1. Power on device
 2. OLED shows: &quot;Unconfigured - Choose method&quot;
 3. User selects WiFi/BLE/OLED provisioning
 4. Configure: Role, Network ID, WiFi credentials
 5. Device saves to NVS, reboots
 6. Joins network based on role
 ```
 
 ### 9.2 Network Formation
 ```
 1. First device becomes ANL (or forced ANL)
 2. Creates WiFi network
 3. Other devices join as configured
 4. ANL builds registry, coordinates ranging
 5. Hot Standby elected automatically
 ```
 
 ### 9.3 Field Maintenance
 - **Role Rotation:** Periodic ANL changes for battery balance
 - **Reconfiguration:** Via OLED menu or web UI
 - **Firmware Updates:** Staggered OTA via ANL
 - **Battery Replacement:** Hot-swappable with graceful shutdown
 
 ## 10. Complete AT Command Integration [1]
 
 ### 10.1 Essential Commands Used
 | Command | Purpose | Our Usage |
 |---------|---------|-----------|
 | `AT+SETCFG` | Device configuration | Set ID and role [1] |
 | `AT+SETCAP` | System capacity | Control refresh rate [1] |
 | `AT+SETPAN` | Network ID | Network segregation [1] |
 | `AT+RANGE` | Distance data | Position computation [1] |
 | `AT+SLEEP` | Power saving | TAG sleep management [1] |
 | `AT+SETPOW` | Transmit power | Optimize battery use [1] |
 
 ### 10.2 Default Configuration
 ```cpp
 // Applied to all devices
 #define DEFAULT_NETWORK_ID  1234
 #define DEFAULT_TAG_CAPACITY 10
 #define DEFAULT_SLOT_TIME   10  // ms
 #define DEFAULT_RATE        1   // 6.8Mbps [1]
 ```
 
 ## 11. Performance Specifications
 
 ### 11.1 System Performance
 - **Position Update:** 1-100Hz (configurable) [1]
 - **Accuracy:** &lt;30cm typical, &lt;10cm optimal [1]
 - **Network Size:** 64 Tags, unlimited Anchors [1]
 - **ANL Failover:** &lt;10 seconds
 - **Join Time:** &lt;30 seconds
 - **Position Latency:** &lt;100ms
 
 ### 11.2 Power Performance
 - **Active Current:** 34mA (UWB) + ESP32-S3 [1]
 - **Sleep Current:** 35µA (UWB sleep) [1]
 - **OLED Current:** 20mA active, &lt;1mA sleep
 - **Battery Life:** 3-48 hours (role/mode dependent)
 
 ### 11.3 Radio Performance
 - **UWB Range:** Up to 100m LOS
 - **WiFi Range:** Typical indoor 30m
 - **BLE Range:** 10m for provisioning
 - **Interference Mitigation:** PAN ID segregation [1]
 
 ## 12. Manufacturing &amp; Testing
 
 ### 12.1 Production Flashing
 1. Base firmware with all capabilities
 2. Test: OLED, UWB, WiFi, BLE, IMU (if present)
 3. Set default PAN ID [1]
 4. Package with battery
 
 ### 12.2 Quality Assurance
 - **UWB Test:** Range accuracy verification
 - **OLED Test:** Full display test pattern
 - **Battery Test:** Charge/discharge cycle
 - **Role Test:** Each role functionality
 - **Provisioning Test:** All methods working
 
 ## 13. Complete Filespec
 
 ### 13.1 Repository Structure
 ```
 rtls-unified-firmware/
 ├── README.md           # This specification
 ├── platformio.ini      # Build configuration
 ├── include/
 │   ├── config.h        # System configuration
 │   ├── roles.h         # Role definitions
 │   └── uwb_at_cmds.h   # AT command wrapper [1]
 ├── src/
 │   ├── main.cpp        # Entry point
 │   ├── drivers/        # Hardware drivers
 │   ├── roles/          # Role implementations
 │   ├── network/        # Networking code
 │   └── services/       # Web/BLE services
 ├── webui/              # Web interface files
 └── tools/
     ├── flasher/        # Production flashing
     └── tester/         # QA testing tools
 ```
 
 ### 13.2 Key Implementation Files
 - `src/roles/anl.cpp` - ANL behavior with registry
 - `src/drivers/ssd1306_ui.cpp` - OLED menu system
 - `src/network/provisioning.cpp` - WiFi+BLE config
 - `src/services/election.cpp` - Leader election
 - `src/drivers/uwb_at.cpp` - AT command interface [1]
 
 ## 14. Appendices
 
 ### 14.1 OLED Display Content by Role
 
 **Anchor:**
 ```
 [ANCHOR 03]
 BATT: 85%
 TAGS: 5/10
 PAN: 1234 [1]
 ```
 
 **Tag:**
 ```
 [TAG 12] &lt;ACTIVE
 POS: 1.2, 3.4, 0.5
 BATT: 72%
 NEAR: A03 (2.1m)
 ```
 
 **ANL:**
 ```
 [ANL] *FORCED*
 NET: RTLS-NET-A3B2
 DEVICES: 8/24
 BATT: 64% (18h)
 ```
 
 ### 14.2 Provisioning State Machine
 ```
 UNCONFIGURED
     ↓ (User action)
 PROVISIONING (WiFi AP/BLE/OLED)
     ↓ (Config complete)
 CONFIGURED
     ↓ (Boot)
 ROLE_EXECUTION
     ↓ (Failure)
 RECOVERY (Diagnostic AP)
 ```
 
 ### 14.3 NVS Storage Layout
 ```
 key                    type    description
 device_role           uint8   ROLE_ANCHOR/TAG/ANL/etc
 wifi_ssid             string  WiFi credentials
 wifi_pass             string
 network_id            uint16  PAN ID [1]
 anl_forced            bool    Manual ANL force
 force_expiry          uint64  Timestamp
 battery_calibration   float   Capacity calibration
 oled_brightness       uint8   Display setting
 ```
 
 ---
 
 ## 15. Summary of All Solutions Implemented
 
 | Requirement | Solution | Status |
 |-------------|----------|--------|
 | Unified hardware | Single MAUWBS3CA1 module | ✅ |
 | Battery operation | 2000mAh LiPo, power management | ✅ |
 | OLED on all devices | SSD1306 with role-specific UI | ✅ |
 | Role selection at boot | NVS storage, provisioning system | ✅ |
 | Any-device ANL | Election algorithm with manual override | ✅ |
 | TAG position offset | IMU fusion with EKF | ✅ |
 | WiFi/BLE provisioning | Multi-method config system | ✅ |
 | UWB integration | AT command wrapper [1] | ✅ |
 | Hot Standby failover | State mirroring, fast promotion | ✅ |
 | Network segregation | PAN ID system [1] | ✅ |
 | Power management | Dynamic scaling, sleep modes | ✅ |
 | Manual ANL forcing | Multiple methods with safety | ✅ |
 | Unified firmware | Single image with role dispatch | ✅ |
 
 ---
 
