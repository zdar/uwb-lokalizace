# UWB RTLS Firmware Specification (DW3000, ESP32-S3)

## 1. Overview

### 1.1 System Description
Indoor RTLS system using UWB (DW3000) with centimeter-level accuracy.

- 3D localization (mandatory)
- TAG computes position
- ANCHOR performs self-validation
- Global coordinate alignment via calibration points
- Firmware identical for all nodes (runtime role switch)

---

## 2. Localization Engine

## 2.1 State Estimation (EKF)

### State Vector
X = [x, y, z, vx, vy, vz]^T

---

### 2.2 Process Model

Constant velocity model:

x_k = x + vx * dt  
y_k = y + vy * dt  
z_k = z + vz * dt  

vx_k = vx  
vy_k = vy  
vz_k = vz  

---

### 2.3 State Transition Matrix (F)

F =
[1 0 0 dt 0  0  
 0 1 0 0  dt 0  
 0 0 1 0  0  dt 
 0 0 0 1  0  0  
 0 0 0 0  1  0  
 0 0 0 0  0  1]

---

### 2.4 Process Noise (Q)

Q = σ_process^2 * Identity(6)

Tunable:
- σ_process ≈ 0.1–1.0

---

## 2.5 Measurement Model (UWB)

Each anchor i:

z_i = sqrt((x - xi)^2 + (y - yi)^2 + (z - zi)^2)

---

### 2.6 Measurement Function

h(X) = [
d1
d2
...
dn
]

---

### 2.7 Jacobian (H)

For anchor i:

∂d/∂x = (x - xi) / di  
∂d/∂y = (y - yi) / di  
∂d/∂z = (z - zi) / di  

Velocity derivatives = 0

---

### 2.8 Measurement Noise (R)

R = diag(σ_uwb^2)

Typical:
- σ_uwb = 0.05–0.15 m

---

## 3. Trilateration Bootstrap

- EKF requires initial estimate
- Initial position computed via:
  - linearized least squares
  - fallback: centroid of anchors

---

## 4. Calibration (Global Alignment)

### 4.1 Problem

Local UWB frame ≠ real-world frame

---

### 4.2 Solution

Rigid transform:

P_global = R * P_local + T

---

### 4.3 Algorithm

Use SVD-based Procrustes:

1. Compute centroids
2. Subtract centroids
3. Compute covariance matrix
4. SVD
5. Compute rotation R
6. Compute translation T

---

### 4.4 Minimum Points

- Required: 4
- Recommended: 6–10

---

## 5. Anchor Self-Validation

- periodic anchor-anchor ranging
- compare with stored reference distances

Trigger:

|d_measured - d_ref| > threshold

---

## 6. IMU Integration (PHASE 2)

### 6.1 State Extension

X = [x y z vx vy vz ax ay az]

---

### 6.2 Fusion

- EKF extended
- IMU used for prediction step
- UWB used for correction

---

## 7. Firmware Architecture

Modules:
- uwb_driver (DW3000)
- ranging_service
- ekf_localization
- calibration_engine
- anchor_monitor
- storage_service
- api_client
- ui_service
- imu_service (optional)

---

## 8. UI (CZ/EN)

### Display:
- Position
- Accuracy
- Anchor count

### Button:
- short press → save + upload

---

## 9. Agent Development

Agents:
- math-agent → EKF, SVD
- fw-agent → drivers
- test-agent → simulation

---

## 10. Constraints

- real-time
- multi-anchor sync
- noise handling critical
