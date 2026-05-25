# UWB PoC Field Test Manual

## Prerequisites
- 5x ESP32-S3 modules flashed with `proof-of-concept` branch firmware
- Laptop with Python 3 installed
- USB cable for serial monitoring (optional but helpful)

---

## Step 1: Flash Firmware

For each module, change `#define UWB_INDEX` in `src/main.cpp` before flashing:

| Module | UWB_INDEX | Role after provisioning |
|--------|-----------|------------------------|
| 0 | 0 | ANL + ANCHOR |
| 1 | 1 | NODE + ANCHOR |
| 2 | 2 | NODE + ANCHOR |
| 3 | 3 | NODE + ANCHOR |
| 4 | 4 | NODE + TAG |

```bash
# Change UWB_INDEX, then:
pio run --target upload
```

---

## Step 2: Provision Roles

### Module 0 (ANL)
1. Power on
2. During the 3-second boot window, **hold button for 2 seconds**
3. OLED shows "SET SYSTEM ROLE"
4. If it shows "NODE", **press button once** to toggle to "ANL"
5. **Hold button for 2 seconds** to save
6. OLED shows "PROVISION SAVED" then reboots

### Modules 1-3 (Anchors)
1. Power on
2. Do NOT enter provisioning — let it boot as NODE (default)
3. After boot, **hold button for 2.5 seconds**
4. OLED shows "ANCHOR" → "Rebooting..."
5. Module reboots as anchor

### Module 4 (Tag)
1. Power on
2. Do NOT enter provisioning — let it boot as NODE (default)
3. After boot, **hold button for 2.5 seconds**
4. OLED shows "TAG" → "Rebooting..."
5. Module reboots as tag

---

## Step 3: Power On Sequence

1. **Power on Module 0 (ANL) first**
   - Wait until OLED shows "ANL Running"
   - Check serial log: `Starting ANL AP: RTLS-NET-1234`

2. **Power on Modules 1-4**
   - Each will join WiFi automatically
   - OLED shows "WIFI CONNECTED" then IP address

---

## Step 4: Connect Laptop

1. Connect laptop to WiFi: `RTLS-NET-1234`
2. Password: `rtlsnet12`
3. Verify connection: `ping 192.168.4.1` should work

---

## Step 5: Start Logger

```bash
cd positioning
python poc_logger.py
```

You should immediately see `[RPT]` lines flowing from the tag.

---

## Step 6: Test SNAP

1. On **Module 4 (Tag)**, **short-press** the boot button
2. **OLED should show:** `5...` → `4...` → `3...` → `2...` → `1...` → `OK`
3. **Logger should show:** a burst of `[SNAP]` lines for 5 seconds
4. Check CSV file: `uwb_log_YYYYMMDD_HHMMSS.csv`

---

## Step 7: Anchor-to-Anchor Distance Matrix (Manual SNAP)

To measure distances between all anchors, temporarily turn each anchor into a TAG, press SNAP, then revert it back to ANCHOR.

### For each anchor (one at a time):
1. **Hold button for 2.5s** on the anchor → OLED shows "TAG" → reboots
2. **Short-press** the button → OLED counts down `5...` → `OK`
3. **Wait for it to finish**
4. **Hold button for 2.5s** again → OLED shows "ANCHOR" → reboots back
5. **Move to next anchor**

### Build the matrix
```powershell
cd positioning
python poc_measure.py
```
This reads the latest `uwb_log_*.csv`, extracts all SNAP data, and prints a median distance matrix between all nodes.

---

## Step 8: Antenna Delay Calibration

1. Place a tag at a **known distance** from all anchors (e.g. exactly 100 cm).
2. Press **SNAP** on the tag.
3. Run:
```powershell
cd positioning
python poc_calibrate.py
```
4. Enter the known distance for each anchor when prompted.
5. The script prints `AT+SETANT=<delay>` for each anchor.
6. Connect to each anchor via USB serial (115200 baud) and send:
   ```
   AT+SETANT=<delay>
   AT+SAVE
   ```

---

## Step 9: Verify CSV

Open the CSV file. You should see:
- `SNAP` rows after button press (contains raw AT+RANGE lines)

Columns: `timestamp_ms, type, tag_id, anchor_id, range_cm, ...`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Laptop can't connect to WiFi | ANL supports max 10 clients. Disconnect other devices. |
| No `[RPT]` lines in logger | Check tag is in TAG mode (hold 2.5s). Check ANL is running. |
| SNAP doesn't show countdown | Make sure you're pressing the button on the TAG, not anchor. |
| Nodes show "WiFi join failed" | Power cycle ANL first, then nodes. Check NETID matches. |
| OLED shows "WIFI JOIN FAILED" | ANL not running or wrong NETID. Check serial logs. |

---

## Button Reference

| Action | Duration | Result |
|--------|----------|--------|
| Short press | < 200ms | Anchor: toggle reporting. Tag: start SNAP. |
| Hold | 2.5s | Toggle TAG/ANCHOR + reboot |
| Hold during boot | 2s | Enter provisioning menu |

---

## Python Scripts Summary

| Script | Purpose | When to run |
|--------|---------|-------------|
| `poc_logger.py` | Listen to UDP broadcast, write CSV | Always running during test |
| `poc_measure.py` | Build distance matrix from CSV | After all anchors have been SNAPped as tags |
| `poc_calibrate.py` | Compute antenna delays from CSV | After calibration SNAP at known distance |

---

## Serial Monitor

Connect USB to any module, open serial monitor at **115200 baud**.

Useful messages to look for:
- `Starting ANL AP: RTLS-NET-1234` — ANL is up
- `WiFi connected` — node joined network
- `[SNAP] 5-second stream started` — tag received SNAP command
- `[RPT] tid=X ranges=Y ancids=Z` — ANL received range report
