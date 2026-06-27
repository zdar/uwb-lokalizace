# 3D Anchor Auto-Calibration & Operation Guide

This guide covers option B: calibrating anchor positions by moving a single tag to known 3D points. Once anchors are fixed, the ANL solves tag positions in 3D and broadcasts them.

---

## 1. What you need

- One MAUWBS3CA1 module configured as **ANL** (Active Network Leader).
- At least **three** other modules configured as **anchors** (four or more recommended for 3D).
- One module configured as a **temporary calibration tag**.
- A PC connected to the RTLS WiFi network.
- Tape measure / marked points in the tunnel.

> The ANL defines the coordinate-system origin `(0, 0, 0)`. All known tag positions must be measured relative to the ANL.

---

## 2. Flash the firmware

### Option A: USB cable

```powershell
python -m platformio run -e esp32s3 -t upload
```

### Option B: Over-the-air (OTA)

Build and discover/flash all nodes:

```powershell
python scripts/ota_flash_all.py
```

Or flash a specific node:

```powershell
python scripts/ota_flash_all.py --ip 192.168.4.2
```

> The default environment is `esp32s3-ota`. If you want USB upload by default, switch `default_envs` in `platformio.ini`.

---

## 3. Configure roles and IDs

1. Power on each module.
2. During the 3-second boot window, **hold the button** to enter provisioning.
3. Use short presses to change values and long holds to confirm:
   - Set one device to **ANL**.
   - Set the others to **NODE**.
   - Set the same **Network ID** on all devices.
4. Assign a **unique UWB index** (`0..9`) to every node. The ANL can be any index, but keep track of which one it is.

The ANL will create a WiFi AP named `RTLS-NET-<NNNN>`. Anchors and the calibration tag will join it automatically.

---

## 4. Prepare the calibration tag

Put the calibration tag into **TAG mode** using the button menu or by sending:

```powershell
python scripts/ota_flash_all.py --ip <tag-ip> --id <tag-index>
```

(optional — only needed if the ID is not already set)

The tag will start sending `AT+RANGE` reports to the ANL.

---

## 5. Define known 3D points

Choose at least **4** distinct points in the tunnel. Measure each point relative to the ANL origin:

- `x`: forward/back distance in cm
- `y`: left/right distance in cm
- `z`: height distance in cm

Write them down, for example:

```
P0: (  0,   0, 100)
P1: (200,   0, 100)
P2: (200, 100, 100)
P3: (  0, 100, 100)
P4: (100,  50,  50)
```

> Use more than 4 points and spread them in 3D space (not all on the same plane) for the most accurate anchor positions.

---

## 6. Run the calibration wizard

Connect your PC to the `RTLS-NET-<NNNN>` WiFi, then run:

```powershell
python scripts/calibrate_anchors.py --tag <tag-id>
```

Example for calibration tag `0`:

```powershell
python scripts/calibrate_anchors.py --tag 0
```

The wizard will:

1. Send `CAL,START` to the ANL.
2. Ask you for each known point as `x,y,z`.
3. Send `CAL,POINT,<tag-id>,<x>,<y>,<z>` to the ANL.
4. Wait for the ANL to collect ranges for 15 seconds.
5. Repeat until you press Enter with no input.
6. Wait for the final collection window to close.
7. Send `CAL,SOLVE` and report the result.

### During the 15-second window

- Keep the tag **still** at the exact measured point.
- Do **not** move it until the script asks for the next point.

### What the ANL does

For each anchor, the ANL builds a list of `(known tag position, median range)` pairs and solves the anchor's 3D position with least-squares trilateration. You will see messages like:

```
[CAL3D] Anchor 1 fixed at 194.87, -2.13, 3.45
```

---

## 7. Verify the result

Open the ANL's serial monitor or read the registry table printed every 5 seconds:

```
========== ANL REGISTRY ==========
Node 0 | ID:0 | IP: 192.168.4.1 | Pos: 0.00,0.00,0.00 [OK]
Node 1 | ID:1 | IP: 192.168.4.2 | Pos: 194.87,-2.13,3.45 [OK]
...
==================================
```

The ANL itself stays at `(0, 0, 0)`. All other anchors should now have realistic `(x, y, z)` coordinates.

---

## 8. Normal operation

After calibration, the ANL automatically solves any tag's 3D position from the ranges it receives:

- With **4+ fixed anchors**, it outputs a 3D position.
- With only **3 fixed anchors**, it falls back to 2D and reports `z = 0`.

The result is broadcast as a `SOL` packet:

```
SOL,<tag-id>,<x>,<y>,<z>
```

### View positions on the PC

Edit `positioning/position.py` and set:

```python
MODE = "sol"
```

Connect your PC to the RTLS WiFi and run:

```powershell
python positioning/position.py
```

A window will show anchors in green and tags in red, with `x, y, z` coordinates.

---

## 9. Manual calibration commands (optional)

You can also drive calibration manually without the wizard:

```powershell
# Start a new session
python scripts/calibrate_anchors.py --start

# Add a point
python scripts/calibrate_anchors.py --tag 0 --point 200,0,100

# Check status
python scripts/calibrate_anchors.py --status

# Solve
python scripts/calibrate_anchors.py --solve

# Cancel
python scripts/calibrate_anchors.py --cancel
```

Wait ~15 seconds between each `--point` and before `--solve` so the ANL can collect ranges.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ERR,CAL,SOLVE` / "Need >=4 points" | Not enough accepted points | Enter at least 4 points and wait for each window to finish. |
| `[CAL3D] Anchor X skipped (only N valid points)` | That anchor was not heard at enough points | Ensure the anchor is powered, has the same Network ID, and is in range of the tag at every point. |
| `[CAL3D] Anchor X solve failed` | Geometry is poor or ranges are noisy | Spread points in 3D, remove outliers, add more points. |
| No `SOL` packets | Less than 3 fixed anchors known | Check the registry table; rerun calibration if anchor positions are missing. |
| `position.py` shows no tags in `sol` mode | PC not on RTLS WiFi or wrong port | Connect to `RTLS-NET-<NNNN>` and check `UDP_PORT`. |
| 2D layouts fail in 3D | All anchors are coplanar | The firmware automatically falls back to 2D if 3D solving fails; make sure at least 3 anchors are fixed. |

---

## 11. Notes

- The ANL is fixed at `(0, 0, 0)`. If you want a different global origin, measure all tag points relative to the ANL and then offset the solved coordinates mentally or in your downstream software.
- `POS` packets now accept an optional `z`: `POS,<x>,<y>,<z>` or `POS,<ip>,<x>,<y>,<z>`.
- `SOL` packets are now 5-field, but the Python viewer also accepts legacy 4-field packets for compatibility.
