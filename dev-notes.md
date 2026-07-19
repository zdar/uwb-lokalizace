# Dev notes

## 2026-06-28 — raw scans CSV was empty
**Status:** Fixed by architecture change (see below).  
Old `data/scans/scans_raw_*.csv` and `data/scans/scans_computed_*.csv` were replaced by a single session CSV.

## 2026-07-19 — unified session CSV
All data is now stored in `sessions/session_YYYYMMDD_HHMMSS.csv`:
- One CSV per calibration/measurement session.
- A new session starts automatically when auto-calibration or manual 3D calibration begins, or manually via the **New session** button.
- Sections: SESSION, TRNY, ANCHORS_RESOLVED, ANCHORS_GLOBAL, TRANSFORM, ANCHOR_RAW, CAL3D_RAW, QR_RAW, QR_COMPUTED.

`esp-cam/qr_scanner.py` no longer writes its own CSV files; it only detects QR codes and notifies `scripts/pc_anl.py`, which handles all storage.

## Future work (do not implement now, just planned)
1. **Kalman filter** for UWB position smoothing.
   - Current position is computed by `trilaterate_3d` / `trilaterate` in `scripts/pc_anl.py` and `positioning/position.py`.
   - Add a Kalman filter per TAG to reduce noise and improve stability.
   - Could live in `pc_anl.py` or in a shared `positioning/filter.py` module.

2. **Gyroscopes / IMU fusion**.
   - MaUWB-ESP32S3 board likely has no IMU, but the TAG module could be extended with an external IMU (e.g., MPU6050/MPU9250).
   - Fuse UWB ranges with IMU acceleration/gyro for better motion tracking and outage handling.
   - This is a hardware + firmware + math task.
