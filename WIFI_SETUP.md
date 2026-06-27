# WiFi Configuration Setup Guide

## Overview

The firmware now supports modular WiFi configuration with support for both the ANL (Anchor Node List) network and your home WiFi network.

## Quick Start

### 1. Create Your Secrets File

Copy the template to create your configuration:

```bash
cp WIFI_SECRETS_TEMPLATE.h src/wifi_secrets.h
```

### 2. Edit `src/wifi_secrets.h`

Open the file and configure your credentials:

```cpp
// For HOME WiFi support (optional)
#define ENABLE_HOME_WIFI 1                          // Enable home WiFi features
#define HOME_WIFI_SSID "your-home-wifi-name"       // Your WiFi SSID
#define HOME_WIFI_PASSWORD "your-wifi-password"    // Your WiFi password

// ANL network (always available)
#define WIFI_AP_PASSWORD "rtlsnet12"                // ANL AP password (can be changed)
#define WIFI_AP_CHANNEL 6                           // WiFi channel
```

### 3. Compile and Upload

```bash
platformio run --target upload
```

### 4. Provision Your Devices

**On device startup:**
- **Short press** (< 0.8 sec): Toggle RPT reporting (anchors only)
- **Long press** (2+ sec): Enter provisioning menu

**In provisioning menu:**

1. **Stage 1 - System Role:**
   - Select: ANL (Access Point) or NODE (Client)
   - Press button to toggle
   - Hold button to proceed to next stage

2. **Stage 2 - WiFi/Network Configuration (when Home WiFi is enabled):**
   - Choose WiFi source: **HOME** or **ANL**
   - Press button to toggle
   - Hold button to proceed

3. **Stage 3 - Network ID (ANL in ANL mode only):**
   - Set Network ID (1000-9999)
   - Press button to increment
   - Hold button to save and reboot

## Configuration Scenarios

### Scenario 1: Home Network Only (No ANL)

Use your home WiFi for all devices:

```cpp
#define ENABLE_HOME_WIFI 1
#define HOME_WIFI_SSID "YourHomeWiFi"
#define HOME_WIFI_PASSWORD "your_password"
```

**Provisioning:**
- Make one device: **ANL** role, use **HOME** WiFi
- Make others: **NODE** role, use **HOME** WiFi
- All devices connect to your home WiFi
- The ANL joins the home network as a station and does not create an AP

### Scenario 2: Flexible Home + ANL Network

Switch between networks per device:

```cpp
#define ENABLE_HOME_WIFI 1
#define HOME_WIFI_SSID "YourHomeWiFi"
#define HOME_WIFI_PASSWORD "your_password"
```

**Provisioning:**
- Each device can choose: HOME or ANL during provisioning stage 2
- ANL devices in HOME mode join your home WiFi as a station (no AP)
- ANL devices in ANL mode create the `RTLS-NET-XXXX` AP
- Perfect for testing and portable setups

### Scenario 3: ANL Network Only (Original)

Keep the original ANL-only network:

```cpp
#define ENABLE_HOME_WIFI 0
```

**Provisioning:**
- Works exactly as before
- Only ANL network available
- Home WiFi features disabled

## Device Behavior

### When ANL Role (systemRole = 1)
- **ANL mode (default):** Creates WiFi Access Point
  - SSID: `RTLS-NET-<NETWORKID>` (e.g., `RTLS-NET-1234`)
  - Acts as central node for calibration
  - Receives heartbeats and position reports
- **Home WiFi mode:** Joins your home WiFi as a station (no AP created)
  - Receives broadcast heartbeats and RPT range reports
  - Calibrates anchors and solves tag positions exactly as on `RTLS-NET`
  - Useful for development with `scripts/pc_anl.py`

### When NODE Role (systemRole = 0)
- Connects to WiFi network
- With home WiFi enabled: Can choose HOME or ANL
- Sends heartbeats and range reports to ANL
- Receives calibration commands

## EEPROM Storage

The firmware stores settings in device memory:

- **Address 0:** UWB Role (TAG/ANCHOR)
- **Address 1:** System Role (ANL/NODE)
- **Address 2-3:** Network ID
- **Address 4:** UWB Index
- **Address 5:** Home WiFi Flag (if enabled)

Settings persist across reboots until changed via provisioning.

## Security Notes

⚠️ **Important:**
- `wifi_secrets.h` is in `.gitignore` - it will NOT be committed
- Keep your credentials safe
- Consider changing `OTA_PASSWORD` from default
- Never share `wifi_secrets.h` in public repositories

## Troubleshooting

| Issue | Solution |
|-------|----------|
| WiFi won't connect | Check SSID/password in `wifi_secrets.h` |
| Devices can't see each other | Ensure all are on same WiFi network |
| Home WiFi option missing | Check `ENABLE_HOME_WIFI 1` is set |
| Device stuck on wrong WiFi | Use provisioning to reconfigure |

## File Reference

- `src/wifi_secrets.h` - ⚠️ Your private credentials (not tracked by git)
- `WIFI_SECRETS_TEMPLATE.h` - Template and documentation
- `src/main.cpp` - Main firmware with WiFi support

## Advanced: Changing Credentials

To update WiFi credentials:

1. Edit `src/wifi_secrets.h`
2. Recompile: `platformio run`
3. Upload: `platformio run --target upload` or OTA
4. Devices use new credentials on next boot

No need to re-provision devices unless changing between HOME/ANL mode.
