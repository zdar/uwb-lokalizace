# PoC Plan: 3D UWB Raw Data Collection

## Architecture (5 modules now, scalable to 8+)

| Module | UWB Index | System Role | UWB Role | Purpose |
|--------|-----------|-------------|----------|---------|
| 0 | 0 | ANL | Anchor | WiFi AP, command orchestrator |
| 1 | 1 | NODE | Anchor | Ranging target |
| 2 | 2 | NODE | Anchor | Ranging target |
| 3 | 3 | NODE | Tag | Fixed tag, button snapshots |
| 4 | 4 | NODE | Tag | Fixed tag, button snapshots |

The UWB module supports up to **8 anchors** and **64 tags**. The firmware uses arrays sized for 8 anchors (`ranges[8]`, `ancids[8]`) so scaling to 8 anchors requires no code changes — only assigning unique `UWB_INDEX` values 0..7 at compile time.

## Key Design Decisions

1. **No trilateration** - pure raw distance data only
2. **No anchor positions stored** - positions computed later from the mesh
3. **Multi-point antenna delay calibration** - module 0 is the fixed reference tag, all others are anchors
4. **Button snapshots** on tags sent via UDP to ANL, logged to CSV on PC
5. **Anchor-to-anchor matrix** via "do ranging" command that cycles anchors to tag mode
6. **Auto-calibration disabled** - no automatic position solving

## Firmware Changes (src/main.cpp)

### 1. Disable Auto-Calibration
- `#define POC_DISABLE_AUTO_CAL 1`
- Skip `autoCalibrateLoop()` entirely

### 2. Multi-Point Antenna Delay Calibration (Restart-Resistant)
**Reference setup:** Module 0 is the fixed reference tag. Modules 1+ are anchors to be calibrated.

**Calibration distances:** 100 cm, 200 cm, 400 cm, 600 cm (add 800 cm if space allows). More points = better fit.

**EEPROM state for restart resistance:**
- `CAL_STATE_ADDRESS` (2 bytes): `0=idle`, `1=waiting_point`, `2=done`
- `CAL_TARGET_ADDRESS` (1 byte): anchor_id being calibrated
- `CAL_POINT_IDX_ADDRESS` (1 byte): which distance point we are on (0..N-1)
- `CAL_DATA_BASE` (64 bytes): stores up to 8 (known_cm, measured_cm) pairs as uint16_t pairs

**Workflow per anchor:**
1. ANL sends `CAL_START,<anchor_id>` to start calibration
2. ANL writes `CAL_STATE=1`, `CAL_TARGET=<anchor_id>`, `CAL_POINT_IDX=0` to EEPROM
3. Anchor displays "CAL: Place at 100cm, press btn" on OLED
4. User places anchor at 100 cm from tag 0, presses button
5. Anchor collects 20-30 `AT+RANGE` samples to tag 0, computes median
6. Anchor sends `CAL_POINT,<anchor_id>,100,<median_cm>` to ANL
7. ANL stores the pair in EEPROM at `CAL_DATA_BASE + point_idx * 4`
8. ANL increments `CAL_POINT_IDX` in EEPROM
9. Repeat for distances 200, 400, 600 cm
10. After all points, ANL reads all pairs from EEPROM, performs linear fit: `measured = a * known + b`
11. `b` is the antenna delay offset in cm. Convert to `AT+SETANT` units and send to anchor
12. Anchor applies `AT+SETANT`, `AT+SAVE`
13. ANL sets `CAL_STATE=2` (done) in EEPROM
14. ANL broadcasts `CAL_DONE,<anchor_id>,<delay>` for logging

**Recovery after reboot:**
- On boot, ANL reads `CAL_STATE` from EEPROM
- If `CAL_STATE=1` (waiting_point), ANL reads `CAL_TARGET` and `CAL_POINT_IDX`
- ANL sends message to the target anchor to resume at the current point
- Anchor displays the correct distance prompt
- No data is lost because all collected points are in EEPROM

**All calibration data is logged:** Every `CAL_POINT` and the final `CAL_DONE` are emitted as structured log lines and saved to CSV by `poc_logger.py`.

**Why multi-point:** A single point assumes perfect linearity. Multiple points verify linearity and give a robust least-squares fit for the delay offset.

### 3. "Do Ranging" - Anchor-to-Anchor Matrix
New UDP command: `MEASURE,ANCHOR_MATRIX`

1. ANL picks first anchor, sends `ROLE,0` (tag mode)
2. Waits for reboot + WiFi rejoin
3. Collects RPT ranges for ~15s (median filter)
4. Sends `ROLE,1` (anchor mode) to restore
5. Repeats for all anchors
6. Outputs: `DIST,from_id,to_id,raw_cm,median_cm,ts`

### 4. Button Snapshots (Tag Side)
Short button press on tag:
1. Captures current `AT+RANGE` data
2. Packages as: `SNAP,<tag_id>,range:(...),ancid:(...),ts`
3. Sends to ANL via UDP
4. ANL logs to serial in CSV format

### 5. Structured Logging
All output is machine-parseable:
```
CAL_POINT,anchor_id,known_cm,measured_cm,ts  # calibration sample
CAL_DONE,anchor_id,delay,ts                  # calibration result
DIST,from,to,raw_cm,median,ts                # inter-node measurement
SNAP,tag_id,range:(...),ts                   # button snapshot
RPT,tag_id,anc_id,raw_cm,rssi,ts             # continuous tag report
```

## Python Tooling

### poc_calibrate.py
- Interactive CLI for antenna delay calibration
- Sends `CAL_START` command
- Monitors `CAL_POINT` and `CAL_DONE` packets
- Displays progress and final delay value

### poc_measure.py
- Sends `MEASURE,ANCHOR_MATRIX`
- Listens for `DIST` packets
- Builds distance matrix, saves CSV

### poc_logger.py (main collector)
- Listens on UDP `0.0.0.0:50000`
- Parses all packet types
- Writes timestamped CSV with columns:
  `timestamp_ms,tag_id,anchor_id,raw_range_cm,rssi_dbm,snap_flag,from_id,to_id`

### poc_visualize_3d.py (optional)
- Matplotlib 3D scatter of anchors and tags

## Implementation Order

| Step | Task | Deliverable |
|------|------|-------------|
| 1 | Create `poc-3d-rawdata` branch | Git branch |
| 2 | Firmware: disable auto-cal | Compiles, no auto-cal |
| 3 | Python: `poc_logger.py` | CSV logging works |
| 4 | Firmware: multi-point AT+SETANT calibration with EEPROM state | `CAL_START`/`CAL_POINT`/`CAL_DONE` works, restart-resistant |
| 5 | Python: `poc_calibrate.py` | Calibration workflow |
| 6 | Firmware: `MEASURE` mode + `DIST` output | Anchor matrix capture |
| 7 | Firmware: button `SNAP` on tags | Button snapshots work |
| 8 | Python: `poc_measure.py` | Matrix capture + CSV |
| 9 | Field test with 5 modules | Validated logs |
