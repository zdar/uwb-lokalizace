@echo off
setlocal

REM Builds the shareable dist\uwb-lokalizace folder.
REM Run this after changing scripts/pc_anl.py, batch files, or static assets.

set "DEST=dist\uwb-lokalizace"

echo Cleaning old dist folder...
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"

echo Copying launcher and setup files...
copy run_gui.bat "%DEST%\"
copy setup.bat "%DEST%\"
copy requirements.txt "%DEST%"

echo Copying user manual...
if exist "Uzivatelska_prirucka.pdf" copy "Uzivatelska_prirucka.pdf" "%DEST%\"

echo Copying Python scripts...
mkdir "%DEST%\scripts"
copy scripts\pc_anl.py "%DEST%\scripts\"
copy scripts\webcam_qr_scanner.py "%DEST%\scripts\"
copy scripts\open_camera.py "%DEST%\scripts\"
copy scripts\calibrate_anchors.py "%DEST%\scripts\"

echo Copying static web assets...
mkdir "%DEST%\scripts\static"
copy scripts\static\jsQR.js "%DEST%\scripts\static\"

echo Copying ESP32-CAM scanner...
mkdir "%DEST%\esp-cam"
copy esp-cam\qr_scanner.py "%DEST%\esp-cam\"

echo.
echo Package ready: %DEST%
echo Zip this folder and copy it to the new PC.
echo On the new PC, run setup.bat, then run_gui.bat.
pause
