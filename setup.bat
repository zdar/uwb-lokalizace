@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo  UWB PC ANL - Setup
echo ==========================================
echo.

REM Check Python is available.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.8 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo During installation, check "Add Python to PATH".
    pause
    exit /b 1
)

REM Check Python version is at least 3.8.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.8 or newer is required.
    python --version
    pause
    exit /b 1
)

python --version

REM The virtual environment is kept locally per user, NOT on the SharePoint/OneDrive folder.
REM This avoids network latency, sync conflicts, and path problems.
set "VENV_DIR=%LOCALAPPDATA%\uwb-lokalizace\venv"
set "REQUIREMENTS=%~dp0requirements.txt"

echo.
echo Installing into: %VENV_DIR%
echo.

if exist "%VENV_DIR%" (
    echo Existing environment found, updating...
) else (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Upgrading pip...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)

echo Installing dependencies from requirements.txt...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%REQUIREMENTS%"
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Setup complete.
echo.
echo  You can now run the GUI by double-clicking:
echo    run_gui.bat
echo ==========================================
pause
