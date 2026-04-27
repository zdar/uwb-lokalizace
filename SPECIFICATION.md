 # MAUWBS3CA1 RTLS System Specification v6.2
 *Adaptive Real-Time Location System with IMU-Driven Power Management & Dynamic Scheduling*
 
 ---
 ## 1. Overview
 ### 1.1 System Design Principles
 1. **Unified Hardware:** All devices are identical MAUWBS3CA1 modules.
 2. **Mandatory OLED:** SSD1306 display on all devices for local UI.
 3. **Battery-Only Operation:** All devices powered by 2000mAh LiPo.
 4. **Runtime Role Selection:** Device role (Anchor/Tag/ANL/Hot Standby) selected at boot via persistent configuration.
 5. **Any-Device ANL:** Any node can become the Active Network Leader.
 6. **Manual ANL Forcing:** Specific device can be forced to become ANL.
 7. **Mandatory IMU:** 9DOF sensor present on Tags only, **critical for motion detection and power management**.
 8. **Anchor Self-Verification:** Anchors periodically switch to TAG mode (**Sequentially**) to measure distances to peers for health and auto-calibration.
 9. **Multi-Provisioning:** Configuration via WiFi AP, BLE, and OLED menu.
 10. **Self-Healing Network:** Automatic leader election and failover with Hot Standby.
 11. **System-Level Oversampling:** Software-based oversampling for noise mitigation, heavily used for anchor-to-anchor distance estimation.
 12. **Dynamic Refresh Rate:** Position update frequency adapts based on motion status detected by the onboard 9DOF IMU.
 13. **Motion-Triggered Wakeup:** Full precision mode (5 Hz) activates immediately upon detection of movement.
 14. **Idle State Management:** System degrades to 1 Hz after 10s of inactivity; enters "Deep Idle" reporting mode after 60s.
 15. **ANL Scheduling Coordination:** ANL dynamically delays anchor verification cycles if active Tag movement is detected.
 16. **Fixed Reference Point Logic:** System mathematically corrects UWB data to ensure the reported position represents a user-defined logical point that remains stationary during device rotation, even if the physical device body moves around that point.
         
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
 - **Refresh Rate:** **Base 5 Hz**, Idle 1 Hz, Deep Idle 0 Hz (Heartbeat only).
 - **Wake-up Latency:** < 50ms from IMU interrupt to UWB ranging start.
 - **Anchor Verification Cycle:** **5 minutes per anchor** (Sequential rotation managed by ANL).
 - **Anchor Verification Delay:** Up to **+5 minutes** extension if >30% of tags are in "Active" state.
 - **Battery Impact:** Significant reduction in idle power consumption via 1 Hz/Deep Idle modes.
 - **Sleep Current:** 35 µA (Tag deep hibernation) [1].
 
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
 
 ### 4.2 Anchor Self-Verification Protocol (Sequential) & Auto-Calibratio
 A **critical feature** for network health and accuracy. **Changed from Parallel/Batch to Sequential.**
 
 1.  **Scheduler (ANL):**
     -   Maintains a queue of all Anchors in the network.
     -   **Interval:** Every **5 minutes**, the ANL selects the next Anchor in the sequence.
     -   **Command Flow:**
         1.  ANL sends command to Target Anchor: `Switch to TAG mode`.
         2.  Target Anchor performs **Oversampled Ranging** against all other Anchors.
         3.  Target Anchor switches back to `Anchor mode`.
     -   **Conflict Avoidance:** Since only one anchor is in "Tag mode" at any given time, there are no RF collisions during the calibration window.
 
 2.  **Out-of-Sequence Verification (On-Demand):**
     -   **Trigger:** A Tag detects that the calculated position deviates significantly from the expected path or that one specific anchor's range is an outlier compared to others.
     -   **Action:** The Tag sends a `REQ_RECALIB_ANCHOR_X` message to the ANL via WiFi/BLE.
     -   **ANL Response:** The ANL immediately interrupts the 5-minute cycle or schedules the specific anchor as the *next* priority item.
 
 3.  **Network Auto-Calibration:**
      *   **Phase 1:** ANL builds a complete anchor-to-anchor distance matrix using the above process.
      *   **Phase 2:** User places a **TAG at known global coordinates** (min 3 points).
      *   At each point, the TAG&#x27;s ranges to all Anchors are recorded.
      *   **Phase 3:** ANL performs a **multilateration back-calculation** to solve for the precise 3D positions of all Anchors in the global coordinate system.
      *   This establishes the network coordinate frame **once**, without manual surveying.
 
 ### 4.3 Dynamic State Machine (Tag Side)
 The Tag firmware manages three distinct operational states based on IMU data:
 
 | State | Condition | Refresh Rate | Action | OLED Indicator |
 | :--- | :--- | :--- | :--- | :--- |
 | **ACTIVE** | Movement detected (Accel > Threshold) | **5 Hz** | Full oversampling, EKF calculation, standard reporting. | `ACT` / `5Hz` |
 | **IDLE** | No movement for **10s** | **1 Hz** | Reduced sampling count, simplified EKF update. | `SLEEP` / `1Hz` |
 | **DEEP_IDLE**| No movement for **60s** | **0 Hz (Calc)** | Stop position calculation. Send only "Heartbeat + Status" packet to ANL. | `STBY` / `60s` |
 
 ### 4.4 ANL Scheduler Logic (Network Side)
 The ANL now acts as a **Traffic Controller** for anchor validation.
 
 1.  **Standard Cycle:** Every 5 minutes, select next anchor for verification.
 2.  **Movement Detection Logic:**
     -   ANL monitors incoming reports. It counts the number of Tags in `ACTIVE` state vs. `DEEP_IDLE`.
     -   **Threshold:** If **>20%** of connected Tags are in `ACTIVE` state (moving):
         -   **Action:** Postpone the next scheduled anchor verification by **5 minutes**.
         -   **Reasoning:** Moving Tags require maximum RF bandwidth and minimal interference. Delaying calibration ensures highest positioning accuracy during dynamic operations.
     -   **Low Activity:** If **<5%** of Tags are moving:
         -   **Action:** Proceed with normal schedule or even accelerate (e.g., every 3 mins) if network is quiet.
 
 ### 4.5 System-Level Oversampling for Noise Mitigation (Updated)
 Implemented in ESP32-S3 firmware to improve measurement accuracy.
 
 1.  **Purpose:** Reduce random noise in UWB range measurements.
 2.  **Integration:** Oversampling count adapts based on State Machine (High in ACTIVE, Low in IDLE).
 3.  **Heavy Use Case - Anchor-to-Anchor Estimation:**
      *   During anchor self-verification, multiple consecutive `AT+RANGE` reports [1] are collected (e.g., 5-10 samples).
      *   A **median filter** is applied to reject outliers.
      *   The filtered distance is used for the anchor distance matrix.
 4.  **Continuous Use Case - TAG Position Recording:**
      *   In `ACTIVE` state, collects multiple `AT+RANGE` samples [1] within the 100ms window.
      *   Filtered ranges are fed into the EKF, yielding a more stable and accurate position output.

 4.  **Implementation (ESP32 Firmware):**
 ```
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
 
 ### 4.6 Network Formation &amp; ANL Election
 - **First Boot:** Device starts in provisioning mode (WiFi AP + BLE).
 - **ANL Election:** Uses a scoring algorithm: `Score = (Battery × 0.4) + (Uptime × 0.2) + (Connectivity × 0.4)`.
 - **Manual Forcing:** Any device can be forced to be ANL via OLED menu, Web UI, or BLE. Setting persists in NVS.
 - **Hot Standby Failover:** Designated standby promotes in &lt;10s if ANL fails.

### **4.7 Tag Position Offset & Orientation Correction**

#### **4.7.1 Problem Definition: The "Fixed Reference" Constraint**
In RTLS applications, the target of interest is often a specific logical point on an object (e.g., the tip of a tool, the center of a worker's chest, or a handle), not the UWB antenna itself.
- **The Physical Reality:** The UWB antenna ($P_{ant}$) is fixed inside the Tag casing. The Reference Point ($P_{ref}$) is a logical point defined by the user.
- **The Constraint:** When the user rotates the device around $P_{ref}$, the antenna $P_{ant}$ traces a circular arc in 3D space.
- **The Error:** Without correction, the raw UWB solution reports the moving antenna position ($P_{ant}$), causing the reported location to "orbit" the true position even if the user is standing perfectly still.
- **The Goal:** Determine the fixed vector $\vec{V}_{local}$ such that the calculated Reference Point ($P_{ref}$) remains **stationary** in the global coordinate system, regardless of how the Tag rotates or swings around it.

$$ P_{ref} = P_{ant} + (R_{global} \times \vec{V}_{local}) = \text{Constant} $$

---
#### **4.7.2 Arbitrary Location Calibration Procedure**
This procedure determines $\vec{V}_{local}$ without requiring known global coordinates. It relies on the geometric principle that **multiple antenna positions generated by rotating around a single fixed point lie on the surface of a sphere centered at that point.**

**Prerequisites:**
- The user must hold or place the Tag such that the **Reference Point ($P_{ref}$)** remains stationary in the global frame.
- The **physical center of the Tag device (and the antenna)** IS ALLOWED to move, provided it rotates around the fixed $P_{ref}$.
- Minimum of **3 distinct orientations** are required.

**Calibration Workflow:**

1.  **Initiation:**
    - User selects `Calibrate Offset` in the OLED menu.
    - System enters `CALIB_MODE`.
    - Display: `Hold Reference Point Still. Rotate Tag.`
    - Minimum 5 samples to be collected

2.  **Data Collection (Rotation Around Fixed Point):**
    - **Sample 1:** User positions the Tag so the Reference Point is stable (e.g., holding a handle steady).
        - Press button. Record: Raw UWB $P_1$, IMU Rotation $R_1$.
        - *Note:* The antenna is at position $P_1$.
    - **Sample 2:** User rotates the Tag body (e.g., 90°) **around the same Reference Point**.
        - *Crucial:* The user may move their hand slightly to rotate the device, but the logical point $P_{ref}$ must not translate.
        - Press button. Record: Raw UWB $P_2$, IMU Rotation $R_2$.
        - *Note:* The antenna has moved to $P_2$ due to rotation.
    - **Sample 3:** User rotates to a third angle.
        - Press button. Record: Raw UWB $P_3$, IMU Rotation $R_3$.
    ...
    - **Sample N:** User rotates to a third angle.
        - Press button. Record: Raw UWB $P_N$, IMU Rotation $R_N$.

3.  **Stability Check (Reference Point Verification):**
    - The system checks if the calculated Reference Points for each sample converge to a single location.
    - If the user accidentally moved the Reference Point (translated their hand), the calculated $P_{ref}$ values will diverge significantly.
    - If divergence > threshold (e.g., 5 cm), the system prompts: `Error: Reference Point Moved. Please hold steady.`

4.  **Back-Calculation Algorithm (Solving for Fixed Center):**
    The algorithm solves for the offset vector $\vec{V}_{local}$ and the global Fixed Point $P_{fixed}$ simultaneously.
    
    For each sample $i$:
    $$ P_{fixed} = P_i + R_i \times \vec{V}_{local} $$
    
    Since $P_{fixed}$ must be constant for all samples, we solve the minimization problem:
    $$ \min_{\vec{V}, P_{fixed}} \sum_{i=1}^{N} || (P_i + R_i \cdot \vec{V}) - P_{fixed} ||^2 $$
    
    This finds the unique vector $\vec{V}_{local}$ that makes all calculated $P_{fixed}$ points coincide, effectively finding the "center of rotation" of the antenna cloud.

5.  **Validation & Storage:**
    - **Residual Error:** The standard deviation of the calculated $P_{fixed}$ points is computed.
        - If $\sigma < 2$ cm: Calibration Successful.
        - If $\sigma > 5$ cm: Calibration Failed (User likely translated the Reference Point).
    - **Storage:** The resulting $\vec{V}_{local}$ is saved to NVS.
    - **Feedback:** OLED displays: `OFFSET SAVED. Ref Point Fixed.`

#### **4.7.3 Runtime Application**
Once calibrated, the firmware applies the correction in real-time:

1.  **Input:** EKF provides $P_{raw}$ (Antenna); IMU provides $R_{current}$.
2.  **Correction:**
    $$ P_{output} = P_{raw} + (R_{current} \times \vec{V}_{local}) $$
3.  **Result:**
    - If the user rotates the Tag around a fixed point (e.g., swinging a tool handle), $P_{output}$ remains **perfectly static**.
    - The system effectively ignores the movement of the antenna and tracks only the movement of the Reference Point.

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
 │   ├── imu_motion_detector/    # **NEW:** Accelerometer threshold & state machine
 │   ├── ekf_positioning/        # EKF engine (Tag only) with oversampling input
 │   ├── role_manager/           # Role state machine, NVS storage
 │   ├── network_provisioning/   # WiFi AP &amp; BLE config services
 │   ├── anl_orchestrator/       # ANL logic, registry, election, **Scheduler**
 │   ├── power_manager/          # Battery monitoring, sleep states
 │   └── signal_processing/      # Oversampling &amp; filtering routines
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
 - **Tag View (Active):** `[TAG 12] Pos: 1.2, 3.4, 0.5 Bat: 85% ACT`
 - **Tag View (Idle):** `[TAG 12] Pos: 1.2, 3.4, 0.5 Bat: 85% IDLE 1Hz`
 - **Tag View (Deep Idle):** `[TAG 12] STBY Bat: 85%`
 - **ANL View:** `[ANL]* Net:RTLS-NET-A1C3 Dev:8/16 Bat:78%`
 - **Hot Standby View:** `[STANDBY] ANL:OK Sync:100%`
 - **Calib Delayed:** `[TAG 12] NET BUSY Calib Delayed`
 - **Calib Running:** `[TAG 12] CHECKING Anchor 03 OK`
   
 ### 7.2 Configuration Menu Tree
 ```
 Main Menu
 ├── Set Role → [Anchor, Tag, ANL, Hot Standby]
 ├── WiFi Settings → [SSID, Password]
 ├── Network ID → [Enter PAN ID] // Links to AT+SETPAN [1]
 ├── Accuracy Settings → [Oversample Count: 5, Filter: Median, Motion Threshold]
 ├── Force ANL Mode → [Enable/Disable]
 ├── Power Management → [Idle Timeout: 10s, Deep Idle Timeout: 60s]
 ├── Offset Calibration → [Start Wizard] 
 │   └── Instructions: "Keep your hand/Reference Point still. Rotate the Tag body around it."
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
 5.  **Tag Offset Calibration:**
    - Hold the Tag by its handle or place it such that the **logical reference point** (e.g., the tip of the tool) is fixed in space.
    - Run `Offset Calibration`.
    - Rotate the Tag body to 3+ angles **around that fixed point**. The physical center of the Tag will move; this is expected.
    - The system calculates the offset that keeps the **Reference Point stationary**.
 6.  **Operational:** System is live. Tags display positions. ANL monitors health and coordinates periodic anchor verification.
 
 ### 8.2 Anchor Self-Verification Schedule (Enhanced)
 + **Frequency:** Every 5 minutes per anchor (Sequential).
 + **Delay Logic:** Up to +5 minutes extension if >30% of tags are active.
 - **Process:** ANL commands each Anchor to switch to Tag mode, perform **oversampled ranging** (multiple `AT+RANGE` [1] samples), and switch back.
 - **Outcome:** ANL maintains a high-confidence distance matrix and health score for each Anchor.
  
 ### 8.3 Operational Scenarios
 1.  **Busy Warehouse (High Movement):** ANL delays calibration to prioritize Tag accuracy.
 2.  **Night Shift (Low Movement):** ANL accelerates calibration schedule as network traffic drops.
 3.  **Emergency Recalibration:** Tag requests immediate check of specific anchor upon anomaly detection.

 ---
 ## 9. API Summary
 ### 9.1 Internal APIs (Module-to-Module)
 - **UWB Ranging Data:** `AT+RANGE` format over UWB radio [1].
 - **WiFi Registry Protocol:** UDP broadcasts for device discovery and heartbeat.
 - **BLE Provisioning Service:** GATT characteristics for writing configuration.
 - **Oversampling Service:** Function calls to `get_oversampled_range()`.
 - **State Reporting:** `POS_FULL`, `POS_REDUCED`, `HEARTBEAT` packet types.
 - **ANL Broadcast:** `NET_CONFIG` packet containing calibration delay status.
 
 ### 9.2 External APIs (System-to-User/Cloud)
 - **ANL Web UI:** HTTP server for network monitoring, calibration triggers, configuration.
 - **Data Export:** JSON stream of Tag positions (WebSocket or REST) from ANL, optionally with accuracy metrics.
 - **Cloud Uplink:** Optional MQTT/HTTPS from ANL to external server.
 
 ---
 ## 10. Revision History
 | Version | Date | Changes |
 |---------|------|---------|
 | v6.5 | 2024-05-20 | **Corrected Calibration Logic.** Explicitly defined that the **Reference Point** must remain stationary while the **Device Body/Antenna** is allowed to move/rotate around it. Updated UI instructions accordingly. |
 | v6.2 | 2024-05-17 | **Dynamic Power Management.** Base rate 5Hz, IMU-driven state machine (Active/Idle/Deep Idle). ANL scheduling coordination based on network load. |
 | v6.1 | 2024-05-16 | Updated to Sequential Verification (1 anchor/5min) and 10Hz base rate. Added Anomaly Trigger. |
 | v6.0 | 2024-05-15 | **Final with Accuracy Improvements.** Integrated Priority 1 (Anchor Self-Verification) and Priority 2 (System-Level Oversampling) features. Full AT command integration [1]. |
 | v5.0 | 2024-05-15 | Consolidated specification with AT command details. |
 | v4.0 | 2024-05-15 | Included unified firmware, role selection, manual ANL forcing. |
 
 ---
 
