# 3D Anchor Auto-Calibration & Operation Guide

This guide covers two ways to calibrate anchor positions and then operate the system in 3D.

- **Mode A — fully automatic:** The ANL switches each anchor to TAG mode, measures anchor-to-anchor distances, and solves positions without any manually measured points.
- **Mode B — known reference points:** You move a single tag to measured 3D points and run the PC wizard.

Once anchors are fixed, the ANL solves tag positions in 3D and broadcasts them.

---

## 1. What you need

- One MAUWBS3CA1 module configured as **ANL** (Active Network Leader).
- At least **three** other modules configured as **anchors** (four or more recommended for 3D).
- For Mode B only: one module configured as a **temporary calibration tag** and a tape measure.
- A PC connected to the RTLS WiFi network (for Mode B and for viewing positions).

> The ANL defines the coordinate-system origin `(0, 0, 0)`. In Mode A the ANL is the origin and the first solved anchor is forced onto the +X axis; the second is forced into the XY plane. In Mode B you measure all points relative to the ANL.

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

The ANL will create a WiFi AP named `RTLS-NET-<NNNN>`. Anchors will join it automatically.

---

## 4. Home WiFi / PC-as-ANL development mode

The same firmware works on the **ANL** or on a **NODE**. For development you can let all modules (including the ANL) join your **home WiFi** instead of creating the `RTLS-NET-XXXX` AP.

### Flash all modules with the unified firmware

```powershell
python -m platformio run -e esp32s3 -t upload
```

Or OTA after the first flash:

```powershell
python -m platformio run -e esp32s3-ota -t upload --upload-port <IP>
```

### Configure roles and IDs

1. **Provision** each module during the 3-second boot window (hold the button):
   - Set one device to **ANL** (or use a PC running `scripts/pc_anl.py` as the ANL).
   - Set the others to **NODE**.
   - In stage 2 choose **HOME** WiFi for every device that should join your home network.
   - An ANL set to **HOME** joins your home WiFi as a station (no AP); an ANL set to **ANL** creates the `RTLS-NET-XXXX` AP as usual.
2. Give every module a **unique UWB index** (`0..9`).
3. Make sure `src/wifi_secrets.h` has `ENABLE_HOME_WIFI 1` and the correct `HOME_WIFI_SSID` / `HOME_WIFI_PASSWORD`.

### Behavior in home WiFi mode

- Every module joins your **home WiFi**.
- No module creates the `RTLS-NET-XXXX` AP.
- All modules broadcast **heartbeats** and tags broadcast **RPT** range reports to the local network broadcast address.
- An ESP32 ANL receives the broadcasts, calibrates anchors, and solves tag positions exactly as it does on `RTLS-NET`.
- A PC on the same home WiFi can run `scripts/pc_anl.py` as an optional GUI for development.

### Run the PC ANL GUI (optional)

```powershell
pip install flask
python scripts/pc_anl.py
```

Open the URL it prints, e.g. `http://192.168.1.42:5000`.

The web GUI lets you:
- **Discover** all nodes on the home WiFi.
- **Switch roles** between TAG and ANCHOR with a button click.
- **Set anchor positions** manually or calibrate them with known tag points.
- **View live tag positions** as `SOL` would normally show.

### Fully automatic calibration in the PC ANL GUI

The GUI also supports Mode A. In panel **4. Auto-calibrate anchors**, pick the origin anchor ID and click **Start auto-calibration**. The PC will:

1. Fix the origin anchor at `(0, 0, 0)`.
2. Switch the next anchor to TAG, wait 40s for UWB reconfiguration.
3. Collect RPT ranges for 20s.
4. Solve the anchor position and switch it back to ANCHOR.
5. Repeat until all discovered anchors are fixed.

You can stop the sequence at any time with **Stop / reset**. If you prefer, you can still use the ESP32 ANL firmware's built-in auto-calibration via `AUTO,1` or `CALAUTO,<id>`.

### Calibrate with the PC ANL GUI

1. Use the GUI to switch one module to TAG.
2. Place it at a measured point and click **Start 15s collection**.
3. Move it to at least 4 different points and repeat.
4. Click **Solve anchors**.
5. Switch the module back to ANCHOR.
6. Done — the PC now knows all anchor positions and solves tag positions live.

---

## 6. Fully automatic 3D calibration

> **Experimental.** The ANL does everything, but role switching can be unreliable on some modules (slow reboots, stuck in TAG mode, missed packets). It is now **disabled by default**. Enable it only when you want to test it.

The ANL picks one anchor at a time, switches it to TAG mode, collects ranges to the anchors that are already fixed, solves its 3D position, and switches it back.

### Enable/disable automatic calibration

Send a UDP command to the ANL:

```powershell
# Enable
python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'AUTO,1',('192.168.4.1',50000))"

# Disable
python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'AUTO,0',('192.168.4.1',50000))"
```

You can also change the compile-time default in `src/main.cpp`:

```cpp
#define AUTO_CALIBRATION_DEFAULT false
```

### Coordinate frame the ANL builds

1. **ANL** = `(0, 0, 0)`.
2. **First anchor** solved = placed on the **+X axis** at the measured distance from the ANL.
3. **Second anchor** solved = placed in the **XY plane** on the +Y side of the X axis.
4. **Third and later anchors** solved in full 3D using the anchors fixed so far.

Because of this, the first two anchors effectively define your X axis and XY plane. Choose the deployment order so this matches your tunnel coordinate system, or rotate/transform the coordinates in your downstream software.

### What you do

1. Make sure all anchors and the ANL are powered and joined to the network.
2. Wait. The ANL automatically starts the sequence.

The ANL serial log will show:

```
[CAL] Target node ID 1 IP 192.168.4.2
[CAL] Sent ROLE,0 (Tag)
[CAL] Window open, collecting RPT...
[AUTO] Node ID 1 fixed at 194.87, 0.00, 0.00
[CAL] Sent ROLE,1 (Anchor)
```

Then it moves to the next anchor. The whole network can be calibrated without any PC interaction.

### Manually trigger one anchor

If you prefer to control exactly which anchor is calibrated and when, send:

```powershell
python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'CALAUTO,2',('192.168.4.1',50000))"
```

This tells the ANL to switch anchor `2` to TAG mode, collect ranges, solve, and switch it back. You can do this one anchor at a time from a phone/laptop UDP client.

### Limitations

- Fully automatic 3D calibration is sensitive to order. The first two anchors define the coordinate frame.
- If an anchor cannot range to enough already-fixed anchors, it will be skipped and tried again later.
- For best 3D accuracy, place anchors so that later ones have a non-zero Z component relative to the first two.
- Some modules take longer than 60 seconds to reboot and reconfigure. If role switching is unreliable, use **Mode B** or manual `CALAUTO,<id>` triggers.

---

## 7. Calibration with a tag at known 3D points

Use this when you have surveyed reference points and want a precise global coordinate frame.

### 7.1 Prepare the calibration tag

Put the calibration tag into **TAG mode** using the button menu or by sending:

```powershell
python scripts/ota_flash_all.py --ip <tag-ip> --id <tag-index>
```

(optional — only needed if the ID is not already set)

The tag will start sending `AT+RANGE` reports to the ANL.

### 7.2 Define known 3D points

Choose at least **4** distinct points. Measure each point relative to the ANL origin:

- `x`: forward/back distance in cm
- `y`: left/right distance in cm
- `z`: height distance in cm

Example:

```
P0: (  0,   0, 100)
P1: (200,   0, 100)
P2: (200, 100, 100)
P3: (  0, 100, 100)
P4: (100,  50,  50)
```

> Spread points in 3D (not coplanar) for the most accurate anchor positions.

### 7.3 Run the calibration wizard

Connect your PC to the `RTLS-NET-<NNNN>` WiFi, then run:

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

## 8. Verify the result

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

## 9. Normal operation

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

## 10. Manual calibration commands (optional)

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

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ERR,CAL,SOLVE` / "Need >=4 points" | Not enough accepted points | Enter at least 4 points and wait for each window to finish. |
| `[CAL3D] Anchor X skipped (only N valid points)` | That anchor was not heard at enough points | Ensure the anchor is powered, has the same Network ID, and is in range of the tag at every point. |
| `[CAL3D] Anchor X solve failed` | Geometry is poor or ranges are noisy | Spread points in 3D, remove outliers, add more points. |
| No `SOL` packets | Less than 3 fixed anchors known | Check the registry table; rerun calibration if anchor positions are missing. |
| `position.py` shows no tags in `sol` mode | PC not on RTLS WiFi or wrong port | Connect to `RTLS-NET-<NNNN>` and check `UDP_PORT`. |
| 2D layouts fail in 3D | All anchors are coplanar | The firmware automatically falls back to 2D if 3D solving fails; make sure at least 3 anchors are fixed. |

---

## 12. Notes

- The ANL is fixed at `(0, 0, 0)`. If you want a different global origin, measure all tag points relative to the ANL and then offset the solved coordinates mentally or in your downstream software.
- `POS` packets now accept an optional `z`: `POS,<x>,<y>,<z>` or `POS,<ip>,<x>,<y>,<z>`.
- `SOL` packets are now 5-field, but the Python viewer also accepts legacy 4-field packets for compatibility.
