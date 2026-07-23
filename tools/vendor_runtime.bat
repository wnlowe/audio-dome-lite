@echo off
setlocal EnableDelayedExpansion

:: Dev-only. Never run this on a target machine -- it populates runtime\
:: (gitignored) with a standalone CPython build for setup.bat to vendor
:: into distributed packages. Re-run whenever the pinned Python version
:: changes. See docs/distribution-plan.md.

set "TOOLS_DIR=%~dp0"
if "%TOOLS_DIR:~-1%"=="\" set "TOOLS_DIR=%TOOLS_DIR:~0,-1%"
for %%I in ("%TOOLS_DIR%\..") do set "REPO_ROOT=%%~fI"
set "RUNTIME_DIR=%REPO_ROOT%\runtime"
set "PY_VERSION=3.12"

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found on PATH. Install uv, or add it to PATH, then re-run.
    pause
    exit /b 1
)

echo Ensuring managed Python %PY_VERSION% is cached by uv...
uv python install %PY_VERSION% --managed-python
if errorlevel 1 (
    echo ERROR: uv python install failed.
    pause
    exit /b 1
)

:: cwd matters here, not just --no-project: uv still prefers a discoverable
:: .venv/pyproject.toml over its managed toolchain when one is findable from
:: cwd (confirmed empirically from this repo's own root, which resolves to
:: the dev .venv instead). %TEMP% has neither, so resolution from there
:: lands on the real managed interpreter.
set "MANAGED_PYTHON="
pushd "%TEMP%"
for /f "usebackq delims=" %%P in (`uv python find --no-project --managed-python %PY_VERSION%`) do set "MANAGED_PYTHON=%%P"
popd
if not defined MANAGED_PYTHON (
    echo ERROR: could not resolve a managed Python %PY_VERSION% interpreter via uv.
    pause
    exit /b 1
)
if not exist "%MANAGED_PYTHON%" (
    echo ERROR: resolved interpreter path does not exist: "%MANAGED_PYTHON%"
    pause
    exit /b 1
)
echo Found managed interpreter: %MANAGED_PYTHON%

for %%F in ("%MANAGED_PYTHON%") do set "MANAGED_ROOT=%%~dpF"
if "%MANAGED_ROOT:~-1%"=="\" set "MANAGED_ROOT=%MANAGED_ROOT:~0,-1%"

if exist "%RUNTIME_DIR%" (
    echo Removing previous vendored runtime...
    rd /s /q "%RUNTIME_DIR%"
)

echo Copying "%MANAGED_ROOT%" to "%RUNTIME_DIR%"...
robocopy "%MANAGED_ROOT%" "%RUNTIME_DIR%" /E /NFL /NDL /NJH /NJS

:: robocopy exit codes: 0-7 = success (various), 8+ = failure
if %ERRORLEVEL% GEQ 8 (
    echo ERROR: robocopy failed with code %ERRORLEVEL%
    pause
    exit /b 1
)

if not exist "%RUNTIME_DIR%\python.exe" (
    echo ERROR: vendored runtime is missing python.exe at "%RUNTIME_DIR%\python.exe"
    pause
    exit /b 1
)

echo Verifying vendored runtime...
"%RUNTIME_DIR%\python.exe" --version
if errorlevel 1 (
    echo ERROR: vendored python.exe failed to run.
    pause
    exit /b 1
)

"%RUNTIME_DIR%\python.exe" -c "import tkinter, pip, venv" 2>nul
if errorlevel 1 (
    echo ERROR: vendored runtime is missing tkinter, pip, or venv.
    pause
    exit /b 1
)

echo.
echo Runtime vendored successfully at "%RUNTIME_DIR%"
