@echo off
setlocal

REM This batch file is designed to live in the project root (e.g. a SharePoint/OneDrive synced folder).
REM It launches the PC ANL GUI using a per-user virtual environment created by setup.bat.
REM It also starts the ESP32-CAM QR scanner so the trny QR scanning screen works in the UI.

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\uwb-lokalizace\venv"

REM Optional: override the ESP32-CAM URL if your camera has a different IP.
REM set "ESP32_CAM_URL=http://192.168.0.159/capture"

echo ==========================================
echo  UWB PC ANL - GUI + ESP-CAM scanner + session sync
echo ==========================================

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first to install the required Python packages.
    echo.
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
echo Project directory: %PROJECT_DIR%
echo.
echo Starting PC ANL GUI, ESP-CAM QR scanner and session sync...
echo.

REM Launch the PC ANL web GUI in its own window.
start "PC ANL - UWB GUI" "%VENV_DIR%\Scripts\python.exe" scripts\pc_anl.py

REM Give the GUI a moment to bind UDP ports before starting the scanner.
timeout /t 2 /nobreak >nul

REM Launch the ESP32-CAM QR scanner in its own window.
if exist "esp-cam\qr_scanner.py" (
    start "ESP-CAM QR Scanner" "%VENV_DIR%\Scripts\python.exe" esp-cam\qr_scanner.py
) else (
    echo WARNING: esp-cam\qr_scanner.py not found. The QR scanner will not start.
)

REM Open the camera web page once PC ANL discovers it.
if exist "scripts\open_camera.py" (
    start "Open ESP32-CAM page" "%VENV_DIR%\Scripts\python.exe" scripts\open_camera.py
) else (
    echo WARNING: scripts\open_camera.py not found. Camera page will not open automatically.
)

REM Launch the session CSV backup/sync tool.
if exist "scripts\session_sync.py" (
    start "Session Sync" "%VENV_DIR%\Scripts\python.exe" scripts\session_sync.py
) else (
    echo WARNING: scripts\session_sync.py not found. Session sync will not start.
)

echo.
echo Services are running in their own windows.
echo Close those windows to stop the services.
echo.
pause
