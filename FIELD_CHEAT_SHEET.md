# UWB Field Test Cheat Sheet

Quick reference for running UWB SNAP collection in the field.

---

## 1. Start Your Computer

### Windows (Recommended for GUI)
1. Boot Windows normally
2. Connect your PC to the **RTLS-NET-XXXX** WiFi (created by the ANCHOR module)
3. Open **PowerShell** or **Command Prompt** as Administrator (for `usbipd` if needed)

### WSL2 (Serial logger only — GUI has UDP issues in WSL)
1. Open **WSL2 terminal** (Ubuntu)
2. Navigate to the project:
   ```bash
   cd ~/UWB/uwb-lokalizace
   ```

---

## 2. Attach USB Modules

### If using WSL2 (serial logger fallback)

**In Windows PowerShell (Admin):**

```powershell
# List USB devices
usbipd list

# Attach a module to WSL (replace <BUSID> with the actual bus ID, e.g. 1-4)
usbipd attach --wsl --busid <BUSID>

# If you get "Device is already attached" errors:
usbipd detach --busid <BUSID>
usbipd attach --wsl --busid <BUSID>

# If ports are ghost/stale, restart WSL completely:
wsl --shutdown
# Then re-open WSL terminal and re-attach
```

**In WSL terminal:**

```bash
# Check which serial ports exist
ls /dev/ttyUSB*
# or
lsusb

# If you see multiple ttyUSB devices but only one module is plugged in,
# the others are stale ghost devices. Fix with:
#   (in Windows PowerShell) wsl --shutdown
# Then re-open WSL and re-attach.
```

### If using Windows natively (for GUI)

Just plug in the USB module. Windows will assign a COM port automatically (e.g. `COM3`).

**Note:** You generally do NOT need USB serial for the GUI — the GUI works over WiFi/UDP.

---

## 3. Primary Method: Web GUI (Recommended)

### Prerequisites
- PC connected to **RTLS-NET-XXXX** WiFi
- Python 3 installed
- Flask installed:
  ```bash
  pip install flask
  ```

### Start the GUI

**Windows terminal (PowerShell / CMD):**
```powershell
cd C:\path\to\uwb-lokalizace\positioning
python poc_webgui.py
```

**Or in WSL (not recommended for GUI due to UDP broadcast issues):**
```bash
cd ~/UWB/uwb-lokalizace/positioning
python3 poc_webgui.py
```

### Open in Browser
The terminal prints a URL like:
```
http://192.168.4.2:5000
```
Open this in any browser.

### Workflow
1. **Discover Nodes** — click the button, wait for the table to populate
2. **Switch Roles** — click "Switch to TAG" on one node (it will reboot)
3. **Wait ~10 seconds** after role switch for the tag to start ranging
4. **Type a comment** (e.g. "Position A, test run 1")
5. **START SNAP (all tags)** — sends UDP trigger, listens 6 seconds, saves CSV
6. **START AUTO LOG** — continuously listens for button-pressed SNAPs
   - Press the button on the tag anytime
   - Each SNAP is logged automatically
   - Click **STOP AUTO LOG** when done
7. **Download CSV** — click the download link

### Where are CSVs saved?
- **Windows:** `C:\path\to\uwb-lokalizace\positioning\uwb_log_YYYYMMDD_HHMMSS.csv`
- **WSL:** `~/UWB/uwb-lokalizace/positioning/uwb_log_YYYYMMDD_HHMMSS.csv`

---

## 4. Fallback Method: Serial Logger

Use this if:
- The GUI doesn't receive UDP packets (common in WSL2)
- You need to log while connected to the module via USB
- You want a simple, reliable, no-WiFi-trigger workflow

**Important:** Do NOT connect to the module's WiFi while using serial logger — the CH340 USB chip tends to re-enumerate (die) when WiFi power draw spikes. Use one or the other.

### Start the Serial Logger

```bash
cd ~/UWB/uwb-lokalizace/positioning
python3 poc_serial_logger.py
```

Or with a specific port:
```bash
python3 poc_serial_logger.py /dev/ttyUSB0
```

### How it works
- It opens the serial port and listens for `AT+RANGE` output
- When a SNAP packet arrives, it parses and writes to CSV
- **You can change the comment anytime** by typing in the terminal and pressing Enter
- The new comment applies to all subsequent SNAP rows

### Workflow
1. Plug in the ANCHOR module via USB (the one that echoes SNAPs to serial)
2. Run `poc_serial_logger.py`
3. Select the correct port
4. Type a comment (e.g. "Position A") and press Enter
5. Press the button on the TAG module
6. The SNAP data is logged automatically
7. Change comment anytime for the next measurement
8. Press `Ctrl+C` to stop and save the CSV

---

## 5. Quick Command Reference

| Task | Command |
|------|---------|
| List USB devices (Windows) | `usbipd list` |
| Attach USB to WSL | `usbipd attach --wsl --busid <BUSID>` |
| Detach USB from WSL | `usbipd detach --busid <BUSID>` |
| Restart WSL | `wsl --shutdown` |
| List serial ports (WSL) | `ls /dev/ttyUSB*` |
| List serial ports (Windows) | Check Device Manager → Ports (COM & LPT) |
| Start web GUI | `python poc_webgui.py` |
| Start serial logger | `python3 poc_serial_logger.py` |
| Install Flask | `pip install flask` |

---

## 6. Troubleshooting

### GUI shows "0 SNAP rows saved"
- **WSL2 NAT blocks incoming UDP broadcasts.** Run the GUI in native Windows instead.
- Make sure your PC is connected to **RTLS-NET-XXXX** WiFi.
- Check that at least one node is in TAG mode.

### Serial logger dies when I connect to WiFi
- This is a known CH340 USB chip issue. The WiFi power spike causes USB re-enumeration.
- **Solution:** Use serial logger OR WiFi/GUI, not both simultaneously.

### Tag 0 not responding
- Wait ~10 seconds after switching the node to TAG role.
- The UWB module needs time to reinitialize after reboot.

### Multiple ghost ttyUSB devices in WSL
- Run `wsl --shutdown` from Windows PowerShell.
- Re-open WSL terminal and re-attach USB with `usbipd attach`.

### "Failed to bind port 50000" in GUI
- Another process is using port 50000.
- Check: `lsof -i :50000` (WSL) or `netstat -ano \| findstr :50000` (Windows)
- Kill the process or wait a few seconds and retry.

### Can't discover nodes
- Make sure all modules are powered on.
- Ensure your PC is on the same network (`192.168.4.x`).
- Try clicking Discover Nodes again — sometimes the first PONG is missed.

---

## 7. File Locations

| File | Path |
|------|------|
| Web GUI | `positioning/poc_webgui.py` |
| Serial logger | `positioning/poc_serial_logger.py` |
| CSV outputs | `positioning/uwb_log_YYYYMMDD_HHMMSS.csv` |
| This cheat sheet | `FIELD_CHEAT_SHEET.md` |

---

## 8. One-Liner Summary

**Best workflow:**
1. Connect PC to `RTLS-NET-XXXX` WiFi
2. Run `python poc_webgui.py` in **Windows** terminal
3. Open browser, discover nodes, switch one to TAG
4. Wait 10s, click **START AUTO LOG**
5. Press button on tag → SNAP logged automatically
6. Click **STOP AUTO LOG**, download CSV

**Fallback workflow:**
1. Plug ANCHOR module into USB
2. Run `python3 poc_serial_logger.py` in WSL
3. Type comment, press Enter
4. Press button on tag → SNAP logged automatically
5. `Ctrl+C` to stop
