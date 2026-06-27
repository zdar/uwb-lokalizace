# Agent Notes

## Firmware modes

A single binary supports two WiFi modes, selected by provisioning the `useHomeWifi` flag.

- **RTLS-NET / tunnel mode (`useHomeWifi = false`)**: ANL creates `RTLS-NET-<NNNN>` AP; NODEs join it.
- **Home WiFi / development mode (`useHomeWifi = true`)**: every module, including an ANL, joins the home WiFi as a station. No AP is created. Tags broadcast `RPT` and all modules broadcast `HB` to the LAN broadcast address.

Both modes can use either an ESP32 ANL or the PC ANL GUI (`scripts/pc_anl.py`).

## Role switching

TAG / ANCHOR role switching (UWB role, not system role) must **not** reboot the ESP32. The UWB module is reconfigured through the existing AT command sequence (`configureUWB()`), which ends with `AT+RESTART` on the UWB chip only.

- UDP `ROLE,<0|1>` handler and serial `AT+ROLE=<0|1>` handler both update `currentRole`, save it to EEPROM, show the role screen, call `configureUWB()`, and then show the ready screen.
- Do **not** add `ESP.restart()` back into these paths — it reloads the old role from EEPROM and breaks remote switching.

## EEPROM policy

Provisioning settings (UWB role, system role, network ID, UWB index, home-WiFi flag) are **loaded** from EEPROM on boot, but they are **never written** at runtime. The `save*` functions are intentionally no-ops.

This means:
- Values stored in EEPROM externally are respected on boot.
- Runtime changes made through the provisioning menu, UDP commands, or serial commands are **not persisted** across ESP32 reboots.
- TAG/ANCHOR role switching works without rebooting the ESP32; the UWB module is reconfigured on the fly via `configureUWB()`.

## PC ANL GUI scope

`scripts/pc_anl.py` is an optional development GUI. It currently supports:

- Discovering nodes on the home WiFi.
- Switching TAG / ANCHOR roles remotely.
- Setting anchor positions manually.
- Calibrating anchors with a tag at known 3D points (Mode B).
- Viewing live solved tag positions.

It does **not** implement fully automatic anchor calibration (Mode A). That state machine lives only in the ESP32 ANL firmware (`autoCalibrateLoop()` / `CALAUTO,<id>`).

## Common gotchas

- An ESP32 configured as ANL will ignore `ROLE,` switch commands; only NODEs accept them. This is fine for PC-as-ANL development where every ESP is a NODE, but confusing if a mixed deployment is discovered by the GUI.
- In home-WiFi mode, heartbeats are sent by all modules, not just NODEs, so the ANL is discoverable too.
