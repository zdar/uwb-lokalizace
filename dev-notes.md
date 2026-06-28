# Dev notes: raw scans CSV is empty

**Date:** 2026-06-28  
**Branch:** `esp-cam`  
**Status:** QR scan + computed CSV works; raw CSV only has header.

## Problem
`data/scans/scans_raw_YYYYMMDD.csv` is created with the correct header, but no data rows are appended. The `scans_computed_YYYYMMDD.csv` file does get rows.

## Likely root cause
In `esp-cam/qr_scanner.py`, `qr_scan_thread()` collects raw RPT samples from `state.rpt_history` during the oversampling window. It should keep all unique packets received in the window.

If the TAG sends RPT packets slower than the sample loop, or if the timing is unlucky, the `latest_rpt` seen during the window is either:
- too old (`rpt_age >= 500 ms`), so it is skipped, or
- the same packet sampled repeatedly.

The `rpt_listener_thread` already populates `state.rpt_history` (a deque), but `qr_scan_thread` does not use it.

## Suggested fix
During the oversampling window, collect **all** RPT packets from `state.rpt_history` whose timestamp falls inside `[window_start, window_end]`.

Current implementation already uses `state.rpt_history` with a unique key per packet. Window duration is controlled by `SAMPLE_WINDOW_MS`.

## Other things to verify
1. `pc_anl.py` is forwarding `RPT` packets to `127.0.0.1:50001`. Check `_forward_sock.sendto(...)` in `scripts/pc_anl.py`.
2. `qr_scanner.py` successfully binds UDP port 50001. It prints `[RPT] nasloucham na portu 50001`.
3. The TAG is actually sending `RPT` packets (check PC ANL live tag table).
4. `CAPTURE_INTERVAL_S = 0.10` and `SCAN_COOLDOWN_MS = 3000` are tuned OK.

## Files involved
- `esp-cam/qr_scanner.py` — main fix here
- `scripts/pc_anl.py` — RPT forwarder
- `data/scans/scans_raw_*.csv` — output to verify

## Small UI improvement (done 2026-06-28)
Added fixed anchors count in `scripts/pc_anl.py` HTML:
- `anchorCount` span showing `Object.keys(data.anchors).length`.

## Future work (do not implement now, just planned)
1. **Kalman filter** for UWB position smoothing.
   - Current position is computed by `trilaterate_3d` / `trilaterate` in `scripts/pc_anl.py` and `positioning/position.py`.
   - Add a Kalman filter per TAG to reduce noise and improve stability.
   - Could live in `pc_anl.py` or in a shared `positioning/filter.py` module.

2. **Gyroscopes / IMU fusion**.
   - MaUWB-ESP32S3 board likely has no IMU, but the TAG module could be extended with an external IMU (e.g., MPU6050/MPU9250).
   - Fuse UWB ranges with IMU acceleration/gyro for better motion tracking and outage handling.
   - This is a hardware + firmware + math task.
