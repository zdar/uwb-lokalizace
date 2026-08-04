@echo off
setlocal

REM Single launcher for the UWB PC ANL GUI.
REM Run setup.bat first on a new PC to create the virtual environment.
REM
REM Camera source is currently fixed to laptop webcam (browser-based).
REM The interactive choice below is commented out; uncomment it to let the user pick.
REM   1 = ESP32-CAM QR scanner
REM   2 = Laptop webcam QR scanner (browser-based, runs inside the Měření page)

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\uwb-lokalizace\venv"

REM Optional overrides (uncomment if needed):
REM set "ESP32_CAM_URL=http://192.168.0.159/capture"
REM set "WEBCAM_INDEX=0"
REM set "WEBCAM_WIDTH=1280"
REM set "WEBCAM_HEIGHT=720"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first to install the required Python packages.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  UWB PC ANL - GUI launcher
echo ==========================================
echo.
echo Camera source: laptop webcam (browser-based)
echo.
set "USE_WEBCAM=1"

REM Optional user choice (commented out for now):
REM echo Choose QR camera source:
REM echo   1 - ESP32-CAM
REM echo   2 - Laptop webcam (browser-based)
REM echo.
REM set /p CAM_CHOICE="Enter 1 or 2 and press Enter: "
REM if "%CAM_CHOICE%"=="2" (
REM     set "USE_WEBCAM=1"
REM ) else (
REM     set "USE_WEBCAM=0"
REM )

cd /d "%PROJECT_DIR%"
echo Project directory: %PROJECT_DIR%
echo.

REM Launch the PC ANL web GUI in its own window.
start "PC ANL - UWB GUI" "%VENV_DIR%\Scripts\python.exe" scripts\pc_anl.py

REM Give the GUI a moment to bind UDP ports before starting the scanner.
timeout /t 2 /nobreak >nul

if "%USE_WEBCAM%"=="1" (
    REM Webcam QR scanning is done inside the browser on the Měření page.
    REM The standalone scripts\webcam_qr_scanner.py is kept as an optional backend
    REM scanner; launch it manually if you prefer the old OpenCV window.
    echo Webcam scanning runs inside the browser window.
) else (
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
)

@REM REM Launch the session CSV backup/sync tool.
@REM if exist "scripts\session_sync.py" (
@REM     start "Session Sync" "%VENV_DIR%\Scripts\python.exe" scripts\session_sync.py
@REM ) else (
@REM     echo WARNING: scripts\session_sync.py not found. Session sync will not start.
@REM )

echo.
echo Services are running in their own windows.
echo Close those windows to stop the services.
echo.
pause
