@echo off
setlocal EnableDelayedExpansion

if not "%~1"=="" (
    echo Removing installation source files at "%~1"...
    rd /s /q "%~1"
)

:: Point this at your bundled/custom Python executable
set "PYTHON_EXE=%~dp0..\.venv\Scripts\pythonw.exe"
set "INSTALL_SCRIPT=%~dp0install.py"

if not exist "%PYTHON_EXE%" (
    echo trying python fallback
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
    if not exist "%PYTHON_EXE%" (
        echo ERROR: Python executable not found at %PYTHON_EXE%
        pause
        exit /b 1
    )
)

if not exist "%INSTALL_SCRIPT%" (
    echo ERROR: Install script not found at %INSTALL_SCRIPT%
    pause
    exit /b 1
)

echo Running ffmpeg check/install...
"%PYTHON_EXE%" "%INSTALL_SCRIPT%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ffmpeg setup failed. See messages above.
    exit /b 1
)

echo.
echo audio-dome-lite setup complete.
exit /b 0