 # MAUWBS3CA1 RTLS System Specification v5.0
 *Complete Unified Real-Time Location System Specification*

 ---
 
 ## 1. Overview
 
 ### 1.1 System Design Principles
 1. **Unified Hardware:** All devices are identical MAUWBS3CA1 modules.
 2. **Mandatory OLED:** SSD1306 display on all devices for local UI.
 3. **Battery-Only Operation:** All devices powered by 2000mAh LiPo.
 4. **Runtime Role Selection:** Device role (Anchor/Tag/ANL/Hot Standby) selected at boot via persistent configuration.
 5. **Any-Device ANL:** Any node can become the Active Network Leader.
 6. **Manual ANL Forcing:** Specific device can be forced to become ANL.
 7. **Optional IMU:** 9DOF sensor present on Tags only, for orientation-aware position offset.
 8. **Anchor Self-Verification:** Anchors periodically switch to TAG mode to measure distances to peers for health and auto-calibration.
 9. **Multi-Provisioning:** Configuration via WiFi AP, BLE, and OLED menu.
 10. **Self-Healing Network:** Automatic leader election and failover with Hot Standby.
 
 ### 1.2 Key Performance Metrics
 - **Positioning Technology:** UWB Time-of-Flight (TWR) [1].
 - **Accuracy:** &lt;10 cm under optimal conditions [1].
 - **RF Band:** CH5 (6489.6 MHz) [1].
 - **Data Rates:** 850 kbps and 6.8 Mbps [1].
 - **Maximum Packet Length:** 1023 bytes [1].
 - **Anchor Capacity:** Unlimited (from firmware v1.1.3) [1].
 - **Tag Capacity:** Maximum 64 tags [1].
 - **Refresh Rate:** Configurable up to 100 Hz [1].
 - **Sleep Current:** 35 µA (Tag deep hibernation) [1].
 - **Working Current:** 34 mA [1].
 
 ---
 
 ## 2. Hardware Specification
 
 ### 2.1 Module Pin Definition &amp; Usage [1]
 
 | Pin | Name | Function in Our System |
 |-----|------|------------------------|
 | 1, 2 | 3V3 | **Power 3.3V.** Critical: Must be 3.3V ±5%. Exceeding damages module [1]. |
 | 3 | I2CSDA | **OLED Data (I²C).** Connected to SSD1306 display. |
 | 4 | I2CSCL | **OLED Clock (I²C).** Connected to SSD1306 display. |
 | 5 | SWCLK | Module download port. For firmware updates. |
 | 6 | SWDIO | Module download port. For firmware updates. |
 | 7, 8, 16 | GND | Ground. |
 | 9 | RUN LED | **System Status Indicator.** Universal for Anchor/Tag [1]. Blinking slowly (1s) = configuring. Blinking fast (0.1s) = working. |
 | 10 | UART2 TX | Reserved. Not used. |
 | 11 | UART2 RX/RESET/WAKEUP | **Multi-function: Role Selection Button &amp; Reset.** Pull down 3 seconds = reset. In Tag sleep, pull down = wake-up [1]. Used for navigating OLED menu. |
 | 12 | TX LED | **UWB Transmit Indicator.** Valid for Anchor only [1]. |
 | 13 | RX LED | **UWB Receive Indicator.** Valid for Anchor only [1]. |
 | 14 | UART1 TX | **Main UART TX.** For sending AT commands to UWB module [1]. |
 | 15 | UART1 RX | **Main UART RX.** For receiving responses from UWB module [1]. |
 
 ### 2.2 Power Requirements
 - **Voltage:** 3.3V ±5% supplied via onboard LDO from battery [1].
 - **Current:** 34 mA (working), 35 µA (Tag deep sleep) [1].
 - **Battery:** 2000mAh LiPo with USB-C charging circuit.
 
 ### 2.3 OLED Display (SSD1306 128x64)
 - **Interface:** I²C using pins 3 (SDA) and 4 (SCL).
 - **Library:** Adafruit_SSD1306.
 - **Content:** Role-specific status, battery level, network info, configuration menu.
 
 ---
 
 ## 3. AT Command System Integration [1]
 
 The UWB module is controlled exclusively via AT commands over UART1 at 115200 bps [1].

  - Essential commands (`AT+SETCFG`, `AT+RANGE`, `AT+SETPAN`, `AT+SLEEP`) from the manual [1].
  - Critical initialization sequence using AT commands.
  - Explanation that system roles map to UWB module roles via `AT+SETCFG=(id),(0:Tag/1:Anchor),...` [1].

 
 ### 3.1 Essential Command Reference [1]
 
 | Command | Parameters | Purpose | Our Usage |
 |---------|------------|---------|-----------|
 | **AT?** | None | Verify serial communication [1] | Initialization test. |
 | **AT+SETCFG** | `(id),(role),(rate),(filter)` | Set device ID, role, rate, filter [1] | **Core:** Set device as Anchor (1) or Tag (0). Enable role switching. |
 | **AT+SETCAP** | `(tag_capacity),(slot_time),(extMode)` | Set system capacity and refresh rate [1] | Control network timing. `rate_hz = 1 / (capacity × slot_time)` [1]. |
 | **AT+SETPAN** | `(network_id)` | Set Network ID for segregation [1] | Isolate multiple RTLS networks. Default: 1111 [1]. |
 | **AT+SAVE** | None | Save configuration to flash [1] | **Required** after any configuration change [1]. |
 | **AT+SETRPT=1** | `(1)` | Enable auto-reporting of ranges [1] | Always enabled. |
 | **AT+RANGE** | Auto-reported | Distance measurement data [1] | Primary data source. Format: `AT+RANGE=tid:x1,mask:x2,seq:x3,range:(x4-x11),ancid:(x20-x27)` [1]. |
 | **AT+SLEEP** | `(ms)` | Set Tag sleep time [1] | Power management for battery-powered Tags. |
 | **AT+SETPOW** | `(gain)` | Configure transmission power [1] | Optimize for range vs. battery. |
 
 ### 3.2 Critical Initialization Sequence
 ```shell
 # For any device (role determined by system, not AT command)
 AT+SETCFG=&lt;ID,&lt;0=Tag/1=Anchor,1,0    # 1 = 6.8Mbps, 0 = filter closed [1]
 AT+SETCAP=10,10,0                      # 10Hz default refresh [1]
 AT+SETPAN=&lt;NETWORK_ID                 # e.g., 1234 [1]
 AT+SAVE                                # Must save [1]
 AT+SETRPT=1                            # Enable auto-reports [1]
 ```


 
 ---
 
 ## 4. System Architecture &amp; Roles
 
 ### 4.1 Device Roles
 All roles run on identical hardware. Role is stored in NVS and applied at boot.
 
 | Role | Key Responsibilities | UWB Role via AT+SETCFG [1] | OLED Display |
 |------|----------------------|-----------------------------|--------------|
 | **ANCHOR** | Provides UWB ranges. No position computation. | `role=1` (Anchor) [1] | Status, ID, battery. |
 | **TAG** | Mobile device. Runs EKF for its own position using IMU offset. | `role=0` (Tag) [1] | Position, battery, nearest anchor. |
 | **ANL (Active Network Leader)** | Network coordinator. Hosts WiFi AP, registry, central services. | `role` based on physical function (1 if stationary, 0 if mobile). | Network topology, device count. |
 | **HOT_STANDBY** | Failover node. Mirrors ANL state, ready for promotion. | `role=0` (Tag, if mobile). | ANL heartbeat status, readiness. |

 **ANL** and **HOT_STANDBY** are now **system-level functionalities** layered on top of the two core UWB roles defined by `AT+SETCFG` [1]:
   - ANL: A device (configured as Anchor `role=1` [1] or Tag `role=0` [1]) that additionally runs network coordination services (WiFi AP, registry).
   - Hot Standby: A device (typically configured as Tag `role=0` [1]) that mirrors the ANL's state and is ready for failover promotion.
 
 ### 4.2 Anchor Self-Verification &amp; Auto-Calibration
 A **critical feature** for network health and setup.
 
 1.  **Periodic Self-Check:**
     *   ANL schedules each Anchor to temporarily switch to **TAG mode**.
     *   Switch: `AT+SETCFG=&lt;id,0,1,0` [1] (Role=0 for Tag).
     *   The Anchor-as-Tag measures distances to neighboring Anchors via `AT+RANGE` [1].
     *   Switch back: `AT+SETCFG=&lt;id,1,1,0` [1] (Role=1 for Anchor).
     *   Reports distance matrix and health score to ANL.
 
 2.  **Network Auto-Calibration:**
     *   **Phase 1:** ANL builds a complete anchor-to-anchor distance matrix using the above process.
     *   **Phase 2:** User places a **TAG at known global coordinates** (min 3 points).
     *   At each point, the TAG&#x27;s ranges to all Anchors are recorded.
     *   **Phase 3:** ANL performs a **multilateration back-calculation** to solve for the precise 3D positions of all Anchors in the global coordinate system.
     *   This establishes the network coordinate frame **once**, without manual surveying.


 
 ### 4.3 Network Formation &amp; ANL Election
 - **First Boot:** Device starts in provisioning mode (WiFi AP + BLE).
 - **ANL Election:** Uses a scoring algorithm: `Score = (Battery × 0.4) + (Uptime × 0.2) + (Connectivity × 0.4)`.
 - **Manual Forcing:** Any device can be forced to be ANL via OLED menu, Web UI, or BLE. Setting persists in NVS.
 - **Hot Standby Failover:** Designated standby promotes in &lt;10s if ANL fails.
 
 ---
 
 ## 5. Firmware Architecture (Unified)
 
 ### 5.1 High-Level Structure
 ```
 firmware/ (ESP-IDF Project)
 ├── main/
 │   └── app_main.c              # Entry point, role dispatcher
 ├── components/
 │   ├── uwb_at_interface/       # Wrapper for AT commands [1]
 │   ├── oled_ui_manager/        # SSD1306 menu &amp; status
 │   ├── imu_fusion/             # 9DOF processing (Tag only)
 │   ├── ekf_positioning/        # EKF engine (Tag only)
 │   ├── role_manager/           # Role state machine, NVS storage
 │   ├── network_provisioning/   # WiFi AP &amp; BLE config services
 │   ├── anl_orchestrator/       # ANL logic, registry, election
 │   └── power_manager/          # Battery monitoring, sleep states
 └── partitions.csv              # Dual OTA partitions
 ```
 
 ### 5.2 UWB Interface Wrapper (Abstracting AT Commands [1])
 ```c
 // uwb_at_interface.h
 typedef enum { UWB_ROLE_ANCHOR = 1, UWB_ROLE_TAG = 0 } uwb_role_t;
 
 void uwb_init_device(uint8_t id, uwb_role_t role);
 bool uwb_switch_role_temporarily(uint8_t id, uwb_role_t temp_role);
 range_data_t uwb_get_range_report(void); // Parses AT+RANGE [1]
 void uwb_enter_sleep(uint32_t duration_ms); // AT+SLEEP [1]
 ```
 
 ### 5.3 Role Manager Pseudocode
 ```c
 void role_manager_task(void *pvParameters) {
     device_role_t role = nvs_read_role();
     
     if (role == ROLE_UNCONFIGURED) {
         start_provisioning_mode(); // OLED menu, WiFi AP, BLE
         return;
     }
     
     switch (role) {
         case ROLE_ANCHOR:
             uwb_init_device(my_id, UWB_ROLE_ANCHOR); // AT+SETCFG [1]
             start_anchor_service(); // Listen for ranges
             oled_show_anchor_status(my_id, battery_level);
             break;
         case ROLE_TAG:
             uwb_init_device(my_id, UWB_ROLE_TAG); // AT+SETCFG [1]
             imu_init();
             start_ekf_thread();
             oled_show_tag_position(last_position, battery);
             break;
         case ROLE_ANL:
             wifi_start_softap();
             start_registry_service();
             start_election_heartbeat();
             oled_show_anl_dashboard(device_count);
             break;
     }
 }
 ```
 
 ---
 
 ## 6. Provisioning System
 
 ### 6.1 Multi-Method Flow
 An unconfigured device offers three entry points:
 1.  **OLED Menu:** Navigate with button (Pin 11) to set Role, WiFi SSID/Password, Network ID.
 2.  **WiFi AP:** Connects to &quot;RTLS-Config-XXXX&quot;, accesses web portal at 192.168.4.1.
 3.  **BLE Service:** Advertises &quot;RTLS-Config&quot;. Mobile app writes configuration.
 
 All methods ultimately write to the same NVS keys: `device_role`, `wifi_ssid`, `wifi_pass`, `network_id`.
 
 ### 6.2 Configuration Parameters
 - **Device Role:** Anchor, Tag, ANL, Hot Standby.
 - **WiFi Credentials:** For joining the ANL&#x27;s network (if not ANL).
 - **Network ID (PAN ID):** Must match AT+SETPAN value for UWB communication [1].
 - **Manual ANL Force Flag:** Boolean to override election.
 
 ---
 
 ## 7. OLED User Interface Specification
 
 ### 7.1 Standard Views
 - **Boot/Provisioning:** &quot;RTLS System. Press button to configure.&quot;
 - **Anchor View:** `[ANCHOR 05] Batt: 92% Tags: 3`
 - **Tag View:** `[TAG 12] Pos: 1.2, 3.4, 0.5 Bat: 85%`
 - **ANL View:** `[ANL]* Net:RTLS-NET-A1C3 Dev:8/16 Bat:78%`
 - **Hot Standby View:** `[STANDBY] ANL:OK Sync:100%`
 
 ### 7.2 Configuration Menu Tree
 ```
 Main Menu
 ├── Set Role → [Anchor, Tag, ANL, Hot Standby]
 ├── WiFi Settings → [SSID, Password]
 ├── Network ID → [Enter PAN ID] // Links to AT+SETPAN [1]
 ├── Force ANL Mode → [Enable/Disable]
 └── Save &amp; Reboot
 ```
 
 ---
 
 ## 8. Deployment &amp; Calibration Procedure
 
 ### 8.1 Step-by-Step Setup
 1.  **Flash Devices:** Upload unified firmware to all MAUWBS3CA1 modules.
 2.  **Configure First Device (ANL):** Use OLED menu to set Role=ANL, set WiFi SSID/Password, set Network ID (e.g., 1234). Device reboots as ANL, creates network &quot;RTLS-NET-XXXX&quot;.
 3.  **Configure Anchors &amp; Tags:** Power each device, use OLED menu to set respective Role and the **same Network ID**. They will join the ANL&#x27;s WiFi network.
 4.  **Anchor Auto-Calibration:**
     *   In ANL&#x27;s web UI, initiate &quot;Network Calibration&quot;.
     *   System automatically performs Anchor self-verification to build distance matrix.
     *   Place a Tag at 3+ known physical locations, press button at each.
     *   ANL computes and broadcasts precise Anchor positions.
 5.  **Operational:** System is now live. Tags display positions. ANL monitors health.
 
 ### 8.2 Anchor Self-Verification Schedule
 - **Frequency:** Every 15 minutes (configurable by ANL).
 - **Process:** ANL sequentially commands each Anchor to switch to Tag mode, measure, and switch back.
 - **Outcome:** ANL maintains a health score for each Anchor and detects if any have moved.
 
 ---
 
 ## 9. API Summary
 
 ### 9.1 Internal APIs (Module-to-Module)
 - **UWB Ranging Data:** `AT+RANGE` format over UWB radio [1].
 - **WiFi Registry Protocol:** UDP broadcasts for device discovery and heartbeat.
 - **BLE Provisioning Service:** GATT characteristics for writing configuration.
 
 ### 9.2 External APIs (System-to-User/Cloud)
 - **ANL Web UI:** HTTP server for network monitoring, calibration triggers, configuration.
 - **Data Export:** JSON stream of Tag positions (WebSocket or REST) from ANL.
 - **Cloud Uplink:** Optional MQTT/HTTPS from ANL to external server.
 
 ---
 
 ## 10. Revision History
 
 | Version | Date | Changes |
 |---------|------|---------|
 | v5.0 | 2024-05-15 | **Consolidated Final Specification.** Integrates AT command details [1] with complete system architecture, OLED UI, provisioning, and the new Anchor self-verification/auto-calibration feature. |
 | v4.0 | 2024-05-15 | Included unified firmware, role selection, manual ANL forcing. |
 | v3.0 | 2024-05-15 | Added multi-provisioning (WiFi/BLE/OLED). |
 
 ---
 
 **Document Status:** Implementation Ready.
 **Hardware Basis:** Makerfabs MAUWBS3CA1 UWB AT Module [1].
 **Core Innovation:** Anchor self-verification via temporary role switching and network auto-calibration via TAG placement.
 
