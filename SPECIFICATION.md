 # MAUWBS3CA1 RTLS System Specification v6.0
 *Complete Unified Real-Time Location System with Enhanced Accuracy Features*
 
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
 11. **System-Level Oversampling:** Software-based oversampling for noise mitigation, heavily used for anchor-to-anchor distance estimation.
 
 ### 1.2 Key Performance Metrics
 - **Positioning Technology:** UWB Time-of-Flight (TWR) two-sided distance measurement [1].
 - **Accuracy:** &lt;10 cm under optimal conditions [1], enhanced by oversampling.
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
 
 ### 3.1 Essential Command Reference [1]
 | Command | Parameters | Purpose | Our Usage |
 |---------|------------|---------|-----------|
 | **AT?** | None | Verify serial communication [1] | Initialization test. |
 | **AT+SETCFG** | `(id),(role),(rate),(filter)` | Set device ID, role, rate, filter [1] | **Core:** Set device as Anchor (1) or Tag (0). Enables role switching for anchor self-verification. |
 | **AT+SETCAP** | `(tag_capacity),(slot_time),(extMode)` | Set system capacity and refresh rate [1] | Control network timing. `rate_hz = 1 / (capacity × slot_time)` [1]. Used to optimize sampling rate for oversampling. |
 | **AT+SETPAN** | `(network_id)` | Set Network ID for segregation [1] | Isolate multiple RTLS networks. Default: 1111 [1]. |
 | **AT+SAVE** | None | Save configuration to flash [1] | **Required** after any configuration change [1]. |
 | **AT+SETRPT=1** | `(1)` | Enable auto-reporting of ranges [1] | Always enabled for continuous data flow. |
 | **AT+RANGE** | Auto-reported | Distance measurement data [1] | **Primary data source for oversampling.** Format: `AT+RANGE=tid:x1,mask:x2,seq:x3,range:(x4-x11),ancid:(x20-x27)` [1]. |
 | **AT+SLEEP** | `(ms)` | Set Tag sleep time [1] | Power management for battery-powered Tags. Valid for Tags only [1]. |
 | **AT+SETPOW** | `(gain)` | Configure transmit power [1] | Optimize for range vs. battery. |
 
 ### 3.2 Critical Initialization Sequence
 ```shell
 # For any device (role determined by system, not AT command)
 AT+SETCFG=&lt;ID,&lt;0=Tag/1=Anchor,1,0    # 1 = 6.8Mbps, 0 = filter closed [1]
 AT+SETCAP=10,10,0                      # 10Hz default refresh [1]
 AT+SETPAN=&lt;NETWORK_ID                 # e.g., 1234 (default is 1111) [1]
 AT+SAVE                                # Must save [1]
 AT+SETRPT=1                            # Enable auto-reports [1]
 ```
 
 ---
 ## 4. System Architecture &amp; Roles
 ### 4.1 Device Roles
 All roles run on identical hardware. Role is stored in NVS and applied at boot. The UWB module itself only recognizes two roles via `AT+SETCFG`: **Tag (0)** and **Anchor (1)** [1].
 
 | System Role | Key Responsibilities | UWB Role via AT+SETCFG [1] | OLED Display |
 |------|----------------------|-----------------------------|--------------|
 | **ANCHOR** | Provides UWB ranges. No position computation. | `role=1` (Anchor) [1] | Status, ID, battery. |
 | **TAG** | Mobile device. Runs EKF for its own position using IMU offset. | `role=0` (Tag) [1] | Position, battery, nearest anchor. |
 | **ANL (Active Network Leader)** | Network coordinator. Hosts WiFi AP, registry, central services. | `role` based on physical function (1 if stationary Anchor, 0 if mobile Tag). | Network topology, device count. |
 | **HOT_STANDBY** | Failover node. Mirrors ANL state, ready for promotion. | Typically `role=0` (Tag, if mobile). | ANL heartbeat status, readiness. |
 
 **ANL** and **HOT_STANDBY** are **system-level functionalities** layered on top of the two core UWB roles defined by `AT+SETCFG` [1].
 
 ### 4.2 Priority 1: Anchor Self-Verification &amp; Auto-Calibration
 A **critical feature** for network health and accuracy, enabled by the role-switching capability of `AT+SETCFG` [1].
 
 1.  **Periodic Self-Check:**
      *   ANL schedules each Anchor to temporarily switch to **TAG mode**.
      *   Switch: `AT+SETCFG=&lt;id,0,1,0` [1] (Role=0 for Tag).
      *   The Anchor-as-Tag measures distances to neighboring Anchors via `AT+RANGE` [1]. The `ancid` fields in the response identify which anchors were measured [1].
      *   Switch back: `AT+SETCFG=&lt;id,1,1,0` [1] (Role=1 for Anchor).
      *   Reports distance matrix and health score to ANL.
 
 2.  **Network Auto-Calibration:**
      *   **Phase 1:** ANL builds a complete anchor-to-anchor distance matrix using the above process.
      *   **Phase 2:** User places a **TAG at known global coordinates** (min 3 points).
      *   At each point, the TAG&#x27;s ranges to all Anchors are recorded.
      *   **Phase 3:** ANL performs a **multilateration back-calculation** to solve for the precise 3D positions of all Anchors in the global coordinate system.
      *   This establishes the network coordinate frame **once**, without manual surveying.
 
 ### 4.3 Priority 2: System-Level Oversampling for Noise Mitigation
 Implemented in ESP32-S3 firmware to improve measurement accuracy.
 
 1.  **Purpose:** Reduce random noise in UWB range measurements by taking multiple samples and applying digital filtering.
 2.  **Heavy Use Case - Anchor-to-Anchor Estimation:**
     *   During anchor self-verification, multiple consecutive `AT+RANGE` reports [1] are collected (e.g., 5-10 samples).
     *   A **median filter** is applied to reject outliers (e.g., from brief NLOS).
     *   The filtered distance is used for the anchor distance matrix, significantly improving calibration accuracy.
 3.  **On-Demand Use Case - TAG Position Recording:**
     *   When a user requests a high-precision position fix (e.g., via button press), the TAG enters an **oversampling mode**.
     *   It collects multiple `AT+RANGE` samples [1] at maximum rate (up to 100 Hz [1]).
     *   Filtered ranges are fed into the EKF, yielding a more stable and accurate position output.
 4.  **Implementation (ESP32 Firmware):**
 ```c
 // Pseudocode for anchor-to-anchor oversampling
 float get_oversampled_anchor_distance(uint8_t target_anchor_id) {
     #define OVERSAMPLE_COUNT 8
     float samples[OVERSAMPLE_COUNT];
     for (int i = 0; i &lt; OVERSAMPLE_COUNT; i++) {
         range_data_t data = uwb_get_range_report(); // Parses AT+RANGE [1]
         for (int j = 0; j &lt; 8; j++) {
             if (data.anchor_ids[j] == target_anchor_id) {
                 samples[i] = data.ranges[j];
                 break;
             }
         }
         delay(10); // ~100Hz max rate [1]
     }
     return median_filter(samples, OVERSAMPLE_COUNT);
 }
 ```
 
 ### 4.4 Network Formation &amp; ANL Election
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
 │   ├── ekf_positioning/        # EKF engine (Tag only) with oversampling input
 │   ├── role_manager/           # Role state machine, NVS storage
 │   ├── network_provisioning/   # WiFi AP &amp; BLE config services
 │   ├── anl_orchestrator/       # ANL logic, registry, election
 │   ├── power_manager/          # Battery monitoring, sleep states
 │   └── signal_processing/      # **NEW:** Oversampling &amp; filtering routines
 └── partitions.csv              # Dual OTA partitions
 ```
 
 ### 5.2 UWB Interface Wrapper (Abstracting AT Commands [1])
 ```c
 // uwb_at_interface.h
 typedef enum { UWB_ROLE_ANCHOR = 1, UWB_ROLE_TAG = 0 } uwb_role_t; // Maps to AT+SETCFG x2 [1]
 void uwb_init_device(uint8_t id, uwb_role_t role);
 bool uwb_switch_role_temporarily(uint8_t id, uwb_role_t temp_role); // For anchor self-verification
 range_data_t uwb_get_range_report(void); // Parses AT+RANGE [1]
 void uwb_enter_sleep(uint32_t duration_ms); // AT+SLEEP [1] (Tag only)
 
 // **NEW: Oversampling interface**
 float uwb_get_oversampled_range(uint8_t target_id, uint8_t sample_count);
 ```
 
 ---
 ## 6. Provisioning System
 ### 6.1 Multi-Method Flow
 An unconfigured device offers three entry points:
 1.  **OLED Menu:** Navigate with button (Pin 11) to set Role, WiFi SSID/Password, Network ID (PAN ID).
 2.  **WiFi AP:** Connects to &quot;RTLS-Config-XXXX&quot;, accesses web portal at 192.168.4.1.
 3.  **BLE Service:** Advertises &quot;RTLS-Config&quot;. Mobile app writes configuration.
 
 All methods write to NVS: `device_role`, `wifi_ssid`, `wifi_pass`, `network_id`. The `network_id` must match the value used in `AT+SETPAN` [1].
 
 ### 6.2 Configuration Parameters
 - **Device Role:** Anchor, Tag, ANL, Hot Standby.
 - **WiFi Credentials:** For joining the ANL&#x27;s network.
 - **Network ID (PAN ID):** Must match AT+SETPAN value [1]. Default: 1111 [1].
 - **Manual ANL Force Flag:** Boolean to override election.
 - **Oversampling Settings (New):** Sample count and filter type for anchor verification and tag precision mode.
 
 ---
 ## 7. OLED User Interface Specification
 ### 7.1 Standard Views
 - **Boot/Provisioning:** &quot;RTLS System. Press button to configure.&quot;
 - **Anchor View:** `[ANCHOR 05] Batt: 92% Tags: 3`
 - **Tag View:** `[TAG 12] Pos: 1.2, 3.4, 0.5 Bat: 85%`
 - **ANL View:** `[ANL]* Net:RTLS-NET-A1C3 Dev:8/16 Bat:78%`
 - **Hot Standby View:** `[STANDBY] ANL:OK Sync:100%`
 - **Accuracy Mode (New):** When Tag is in oversampling mode: `[TAG 12] *HIGH-PREC*`
 
 ### 7.2 Configuration Menu Tree
 ```
 Main Menu
 ├── Set Role → [Anchor, Tag, ANL, Hot Standby]
 ├── WiFi Settings → [SSID, Password]
 ├── Network ID → [Enter PAN ID] // Links to AT+SETPAN [1]
 ├── Accuracy Settings → [Oversample Count: 5, Filter: Median]
 ├── Force ANL Mode → [Enable/Disable]
 └── Save &amp; Reboot
 ```
 
 ---
 ## 8. Deployment &amp; Calibration Procedure
 ### 8.1 Step-by-Step Setup
 1.  **Flash Devices:** Upload unified firmware to all MAUWBS3CA1 modules.
 2.  **Configure First Device (ANL):** Use OLED menu to set Role=ANL, set WiFi SSID/Password, set Network ID (e.g., 1234). Device reboots as ANL, creates network &quot;RTLS-NET-XXXX&quot;.
 3.  **Configure Anchors &amp; Tags:** Power each device, use OLED menu to set respective Role and the **same Network ID**. They join the ANL&#x27;s WiFi network.
 4.  **Anchor Auto-Calibration (with Oversampling):**
      *   In ANL&#x27;s web UI, initiate &quot;High-Accuracy Network Calibration&quot;.
      *   System performs anchor self-verification **with oversampling** to build a precise distance matrix.
      *   Place a Tag at 3+ known physical locations, press button at each.
      *   ANL computes and broadcasts precise Anchor positions.
 5.  **Operational:** System is live. Tags display positions. ANL monitors health and coordinates periodic anchor verification.
 
 ### 8.2 Anchor Self-Verification Schedule (Enhanced)
 - **Frequency:** Every 15 minutes (configurable by ANL).
 - **Process:** ANL commands each Anchor to switch to Tag mode, perform **oversampled ranging** (multiple `AT+RANGE` [1] samples), and switch back.
 - **Outcome:** ANL maintains a high-confidence distance matrix and health score for each Anchor.
 
 ---
 ## 9. API Summary
 ### 9.1 Internal APIs (Module-to-Module)
 - **UWB Ranging Data:** `AT+RANGE` format over UWB radio [1].
 - **WiFi Registry Protocol:** UDP broadcasts for device discovery and heartbeat.
 - **BLE Provisioning Service:** GATT characteristics for writing configuration.
 - **Oversampling Service (New):** Function calls to `get_oversampled_range()` for high-precision needs.
 
 ### 9.2 External APIs (System-to-User/Cloud)
 - **ANL Web UI:** HTTP server for network monitoring, calibration triggers, configuration.
 - **Data Export:** JSON stream of Tag positions (WebSocket or REST) from ANL, optionally with accuracy metrics.
 - **Cloud Uplink:** Optional MQTT/HTTPS from ANL to external server.
 
 ---
 ## 10. Revision History
 | Version | Date | Changes |
 |---------|------|---------|
 | v6.0 | 2024-05-15 | **Final with Accuracy Improvements.** Integrated Priority 1 (Anchor Self-Verification) and Priority 2 (System-Level Oversampling) features. Full AT command integration [1]. |
 | v5.0 | 2024-05-15 | Consolidated specification with AT command details. |
 | v4.0 | 2024-05-15 | Included unified firmware, role selection, manual ANL forcing. |
 
 ---
 
