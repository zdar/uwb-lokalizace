@echo off
setlocal

REM Launcher that uses the laptop webcam QR scanner instead of the ESP32-CAM.
REM It reuses run_gui.bat with USE_WEBCAM=1.

set "USE_WEBCAM=1"
call "%~dp0run_gui.bat"
