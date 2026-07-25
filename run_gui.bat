@echo off
setlocal

REM This batch file is designed to live in the project root (e.g. a SharePoint/OneDrive synced folder).
REM It launches the PC ANL GUI using a per-user virtual environment created by setup.bat.
REM It can use either the ESP32-CAM QR scanner or the laptop webcam QR scanner.

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\uwb-lokalizace\venv"

REM Choose camera source. Set USE_WEBCAM=1 to use the laptop webcam instead of ESP32-CAM.
REM run_gui_webcam.bat sets this for you.
if "%USE_WEBCAM%"=="" set "USE_WEBCAM=0"

REM Optional: override the ESP32-CAM URL if your camera has a different IP.
REM set "ESP32_CAM_URL=http://192.168.0.159/capture"

REM Optional: override the webcam index or resolution if the default camera is not suitable.
REM set "WEBCAM_INDEX=0"
REM set "WEBCAM_WIDTH=1280"
REM set "WEBCAM_HEIGHT=720"
REM set "WEBCAM_PREVIEW=1"

if "%USE_WEBCAM%"=="1" (
    echo ==========================================
    echo  UWB PC ANL - GUI + webcam QR scanner + session sync
    echo ==========================================
) else (
    echo ==========================================
    echo  UWB PC ANL - GUI + ESP-CAM scanner + session sync
    echo ==========================================
)

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
if "%USE_WEBCAM%"=="1" (
    echo Starting PC ANL GUI, laptop webcam QR scanner and session sync...
) else (
    echo Starting PC ANL GUI, ESP-CAM QR scanner and session sync...
)
echo.

REM Launch the PC ANL web GUI in its own window.
start "PC ANL - UWB GUI" "%VENV_DIR%\Scripts\python.exe" scripts\pc_anl.py

REM Give the GUI a moment to bind UDP ports before starting the scanner.
timeout /t 2 /nobreak >nul

if "%USE_WEBCAM%"=="1" (
    REM Launch the laptop webcam QR scanner in its own window.
    if exist "scripts\webcam_qr_scanner.py" (
        start "Webcam QR Scanner" "%VENV_DIR%\Scripts\python.exe" scripts\webcam_qr_scanner.py
    ) else (
        echo WARNING: scripts\webcam_qr_scanner.py not found. The QR scanner will not start.
    )
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
