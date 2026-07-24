# UWB PC ANL — User GUI Guide

A step-by-step guide for operators. Print this page and keep it next to the PC.

---

## 1. Before you start

1. **Turn on all 10 UWB modules.** Wait until their screens show ready/heartbeat.
2. **Make sure the PC and all modules are on the same WiFi.** The GUI shows the PC IP when it starts.
3. **Place the ESP32-CAM** so it can see the area where QR codes will be scanned.
4. **Do not move the modules** during calibration unless the procedure tells you to.

---

## 2. Start the GUI

1. Double-click **`run_gui.bat`** in the project folder.
2. A black window opens and shows:
   ```
   Open browser at: http://192.168.0.100:5000
   ```
3. Open that address in a web browser (Chrome/Edge).

If the browser says "page not found", wait 5 seconds and refresh.

---

## 3. User mode: normal workflow

The GUI starts in **user mode** automatically. Use the big buttons.

### 3.1 Place the anchors

1. The first screen says **"Rozmísti krabičky"** (Place the boxes).
2. Physically place the 10 modules where you want them.
3. Click **"Kalibrovat"**.

### 3.2 Wait for auto-calibration

1. The GUI discovers the modules on the network.
2. It then switches each module to TAG, measures ranges, and solves its position.
3. A timer and status message are shown. Do not touch the modules.
4. When it finishes you see:
   - **Green** — anchors that were calibrated successfully.
   - **Red** — anchors that failed.
5. If there are failed anchors, click **"Zkusit znovu selhané"** (Retry failed).

### 3.3 Keep or restart calibration

- If calibration looks good, click **"Pokračovat k trnům"**.
- If you want to start over, click **"Nová kalibrace"**.

### 3.4 Calibrate to real-world coordinates (trny)

1. You are now on the **"Trny"** screen.
2. Point the ESP32-CAM at the first known reference QR code (e.g., `TRN-A1`).
3. When the camera reads the code, the GUI collects UWB ranges for a few seconds and saves the point.
4. Scan at least **3 different trny points**.
5. Click **"Spočítat transformaci"** (Compute transform).
6. The transform is saved automatically.

### 3.5 Measure positions

1. Go to the **"Měření"** screen.
2. Place the TAG module where you want to measure.
3. The live position appears in the table.
4. To measure a point without a QR code, type the code in the **"Manuální spušť"** box and click the button.

---

## 4. Developer mode

For advanced users only.

1. Click **"Vývojářský režim"** on any screen.
2. The full control panel appears with these sections:

### 4.1 Discover / control nodes
- Click **"Discover nodes"** to find modules.
- You can manually switch any module between **TAG** and **ANCHOR**.

### 4.2 Anchor positions
- Manually type X, Y, Z for an anchor and click **"Set anchor"**.
- Click **"Save anchors"** / **"Load anchors"** to use `anchors.json`.

### 4.3 Calibrate anchors with known tag points (Mode B)
1. Pick a module as TAG.
2. Place it at a measured point.
3. Enter X, Y, Z and click **"Start 15s collection"**.
4. Repeat for at least 4 points.
5. Click **"Solve anchors"**.

### 4.4 Auto-calibrate anchors (Mode A)
1. Enter an **Origin anchor ID** (usually 0).
2. Click **"Start auto-calibration"**.
3. Wait until it finishes.

### 4.5 Live tag positions
- Shows real-time positions of all active tags.

### 4.6 Map to real world (trny)
- Click **"Compute transform"** after scanning trny QR codes.
- Click **"Clear transform"** to remove it.

---

## 5. Important buttons

| Button | What it does |
|---|---|
| **Kalibrovat** | Starts anchor auto-calibration in user mode. |
| **Pokračovat k trnům** | Keeps current calibration and opens trny scanning. |
| **Nová kalibrace** | Deletes saved anchors/transform and starts fresh. |
| **Spočítat transformaci** | Computes UWB-to-global transform from scanned trny points. |
| **New session** | Creates a new CSV file pair for logging. |
| **Discover nodes** | Finds modules on the network. |
| **Save anchors** | Saves anchor positions to `anchors.json`. |
| **Load anchors** | Loads anchor positions from `anchors.json`. |

---

## 6. Where data is saved

- Raw measurements: `sessions/session_YYYYMMDD_HHMMSS_raw.csv`
- Solved results: `sessions/session_YYYYMMDD_HHMMSS_solved.csv`
- Anchor positions: `anchors.json`
- Global transform: `transform.json`

---

## 7. Quick troubleshooting

| Problem | What to do |
|---|---|
| Browser cannot connect | Make sure `run_gui.bat` is running. Check the PC IP did not change. |
| "Discover nodes" finds nothing | Check that modules are on the same WiFi and powered on. |
| Auto-calibration fails on many anchors | Make sure modules have clear line of sight. Retry failed anchors. |
| QR code is not read | Check ESP32-CAM view and lighting. Try manual trigger. |
| Position jumps or is wrong | Check anchor positions and transform. Start a new session. |
| CSV files are not created | Click **"New session"** first. |

---

## 8. Tips

- Always start a **new session** before a new measurement campaign.
- Do not change module positions after calibration unless you recalibrate.
- Save anchors after a successful calibration.
- In reflective environments, raise modules 10–15 cm above metal surfaces.
