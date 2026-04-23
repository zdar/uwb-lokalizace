# RTLS System Specification (MAUWBS3CA1)

## 1. Overview

This document defines a multi-node Real-Time Location System (RTLS) based on:

- MAUWBS3CA1 modules (ESP32-S3 + UWB DW3000 abstraction)
- WiFi primary communication network
- Unified firmware for all devices
- Runtime role selection (TAG / ANCHOR)
- BLE for provisioning and recovery

### Key Principles

- All devices run identical firmware image
- Role (TAG or ANCHOR) is selected by user at startup
- Default role is ANCHOR
- Multiple TAGs are supported
- Exactly one TAG acts as Active Network Leader (ANL) at runtime
- WiFi is primary communication backbone
- UWB is used only for ranging
- BLE is fallback + provisioning channel
- System must operate without external WiFi

---

## 2. Hardware Platform

### MAUWBS3CA1 Module

- ESP32-S3 MCU
- Integrated DW3000 UWB (abstracted via AT commands)
- WiFi 802.11 b/g/n
- BLE 5
- 9DOF IMU sensor (accelerometer + gyroscope + magnetometer)
- Supports AP + STA (limited concurrent mode)

---

## 3. Multi-TAG System Architecture

## 3.1 TAG Roles

### Active Network Leader (ANL)

- Exactly one TAG is ANL at runtime
- Creates WiFi SoftAP RTLS network
- Maintains system registry
- Performs EKF localization
- Handles external cloud uplink
- Coordinates other TAGs

### Follower TAG

- Connects to ANL via WiFi (STA mode)
- Provides local control UI
- Can request ANL takeover

### ANCHOR (Slave Node)

- Connects to ANL WiFi network
- Provides UWB ranging data

---

## 3.2 Leader Election Model

- Applies only to TAG devices
- ANL is selected dynamically at runtime

Trigger conditions:

- ANL failure
- manual override
- split network detection

Mechanism:

- BLE heartbeat between TAG devices
- scoring based on uptime and connectivity

---

## 3.3 Network Topology

```
            External WiFi (optional)
                    ↑
                    │
               ANL TAG (WiFi AP + STA)
              /             \
     Follower TAGs        Anchors (STA)
              \             /
               UWB RTLS Layer
```

---

## 4. WiFi Architecture

## 4.1 RTLS Network (Primary)

- Created only by ANL TAG
- Anchors + follower TAGs connect as STA clients

SSID:
```
RTLS_NET_<ANL_ID>
```

---

## 4.2 External Uplink (Secondary)

- Only ANL TAG uses STA mode for internet
- Used for:
  - cloud logging
  - OTA updates
  - analytics

---

## 4.3 Dual WiFi Constraints

- Shared RF interface
- AP + STA concurrency required
- RTLS traffic has highest priority

---

## 5. Communication Architecture

## 5.1 Transport Layers

- WiFi (primary runtime network)
- BLE (provisioning + fallback + leader coordination)

---

## 5.2 Data Flow

Anchors → ANL TAG:
- UWB measurements
- validation data

Follower TAG → ANL TAG:
- UI commands
- status queries

ANL TAG → Anchors / Followers:
- configuration
- calibration
- network state

ANL TAG → Cloud:
- aggregated RTLS data

---

## 6. UWB System

- Managed via MAUWBS3CA1 AT interface
- Localization computed at TAG (ANL)
- Anchors provide range measurements

State vector (base):

X = [x, y, z, vx, vy, vz]

---

## 7. TAG Position Offset & 9DOF Integration (NEW)

## 7.1 Problem Definition

The TAG antenna is not colocated with the defined reference point used for localization.

Therefore:

- UWB position corresponds to antenna position
- System requires correction to reference point position

---

## 7.2 Known Offset Model

Offset is pre-defined at calibration time:

P_ref = P_antenna + R(orientation) * O_fixed

Where:

- O_fixed = known 3D offset vector (antenna → reference point)
- R = rotation matrix from 9DOF orientation

---

## 7.3 9DOF Sensor Usage

The 9DOF IMU provides:

- roll, pitch, yaw (orientation estimate)

Used for:

### 1. Offset transformation

Applies directional correction of fixed offset

### 2. Motion smoothing

- gyro integration improves short-term stability

### 3. Heading-based filtering

- improves EKF prediction model

---

## 7.4 Enhanced State Model (TAG)

Extended state (TAG only):

X = [x, y, z, vx, vy, vz, yaw]

(optional roll/pitch internally used)

---

## 7.5 Sensor Fusion

TAG localization uses:

- UWB (absolute position input)
- EKF (state estimation)
- 9DOF IMU (orientation + short-term prediction)

Fusion strategy:

- UWB = correction term
- IMU = prediction + orientation transform

---

## 7.6 Output Position

Final published TAG position:

P_ref (reference point)

not antenna position

---

## 8. Localization Engine

- Extended Kalman Filter (EKF)
- Centralized at ANL TAG
- Orientation-aware prediction model

---

## 9. Calibration System

## 9.1 Objective

Map local UWB coordinates to global coordinate system:

P_global = R * P_local + T

---

## 9.2 Multi-TAG Calibration

- Calibration collected by ANL TAG
- Single global solution computed centrally

---

## 10. Anchor Validation System

- Anchor-to-anchor consistency checks
- Graph-based error model
- Reports sent to ANL TAG

---

## 11. BLE System

- provisioning
- recovery
- leader coordination between TAGs

---

## 12. WiFi Provisioning

- Role selection at boot
- ANL TAG distributes network config

---

## 13. Network Discovery

- DHCP for IP assignment
- mDNS optional
- heartbeat synchronization over WiFi

---

## 14. Failure Handling

- ANL failover via BLE election
- RTLS network re-established automatically

---

## 15. RTLS Network Registry

Maintained by ANL TAG:

```json
{
  "id": 3,
  "ip": "192.168.10.105",
  "type": "anchor",
  "status": "online"
}
```

TAG entries:

```json
{
  "id": "TAG_02",
  "role": "follower",
  "status": "active"
}
```

---

## 16. External Server Communication

- Only ANL TAG uploads data

---

## 17. UI System

- role selection at boot
- TAG shows ANL/follower status
- web UI available via ANL only

---

## 18. State Machines

- BOOT
- ROLE_SELECTION
- ANCHOR_MODE (default)
- TAG_MODE
- OPERATION
- LEADER_ELECTION

---

## 19. Firmware Modules (UNIFIED)

- wifi_manager
- uwb_interface
- ekf_localization
- imu_9dof_fusion
- ble_stack
- network_orchestrator
- calibration_engine
- validation_engine
- ui_service

TAG-only runtime:

- ap_manager
- leader_election_service
- cloud_uplink_service

---

## 20. Performance Constraints

- unified firmware for all devices
- single ANL AP per network
- RTLS traffic prioritized over cloud traffic
- sensor fusion must be real-time deterministic

---

## 21. Key Design Constraints

- identical firmware for TAG and ANCHOR
- role selected at startup (default ANCHOR)
- multiple TAGs supported
- ANL dynamically elected
- TAG position is corrected using IMU offset model

---

## 21.1 Automatic Network Georeferencing via TAG Placement

## 21.1.1 Concept

The RTLS system supports automatic establishment of global coordinate system using controlled placement of a TAG device at predefined reference positions.

This process enables full network initialization without prior anchor calibration.

---

## 21.1.2 Procedure

1. User places a TAG (in TAG mode) at known physical coordinates
2. System records:
   - UWB measurements from anchors
   - IMU orientation data
   - known global position of TAG

3. Repeat for multiple reference points:
   - minimum: 3 (2D), 4 (3D)
   - recommended: 6–10 points

---

## 21.1.3 Computation

The system solves global transform:

P_global = R * P_local + T

Where:

- P_local = UWB-derived position
- P_global = known reference position
- R, T = solved via SVD (Procrustes alignment)

---

## 21.1.4 Multi-TAG Support

- Any TAG can be used as calibration probe
- Multiple TAGs may contribute simultaneously
- ANL TAG aggregates and solves final global model

---

## 21.1.5 IMU Enhancement

During placement:

- 9DOF IMU provides orientation constraint
- reduces ambiguity in rotation matrix estimation
- improves stability in under-constrained geometries

---

## 21.1.6 Output

After completion:

- all anchors receive global coordinate transform
- TAGs synchronize calibrated frame
- EKF localization switches to global frame

---

## 21.1.7 Failure Handling

- insufficient points → calibration rejected
- high residual error → re-sample required
- outlier detection via residual thresholding

---

## 22. Summary

This RTLS system is a multi-node, multi-TAG architecture with:

- unified firmware across all devices
- WiFi primary communication network
- TAG-based orchestration with leader election
- UWB-based ranging only
- IMU-based orientation and position offset correction
- BLE for provisioning and recovery
- fully self-healing distributed system
