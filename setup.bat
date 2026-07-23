@echo off
setlocal EnableDelayedExpansion

set "SOURCE=%~dp0"
if "%SOURCE:~-1%"=="\" set "SOURCE=%SOURCE:~0,-1%"
set "APPNAME=audio-dome-lite"
set "DEST=%LOCALAPPDATA%\%APPNAME%"

if not exist "%DEST%" (
    mkdir "%DEST%"
)

set "EX_DIR=.git .venv runtime"
set "EX_FILES=.gitignore .python-version pyproject.toml uv.lock requirements.txt"

echo Moving files from "%SOURCE%" to "%DEST%"...
robocopy "%SOURCE%" "%DEST%" /E /NFL /NDL /NJH /NJS /XF "%~nx0" /XD %EX_DIR% /XF %EX_FILES%

:: robocopy exit codes: 0-7 = success (various), 8+ = failure
if %ERRORLEVEL% GEQ 8 (
    echo ERROR: robocopy failed with code %ERRORLEVEL%
    pause
    exit /b 1
)

echo Move complete. Files now in "%DEST%"

:: The dev .venv (excluded above) is built by uv, whose pythonw.exe/python.exe
:: are trampoline stubs that re-exec a console-mode child interpreter on
:: every launch. LocalServer32 activation runs this on every single verb
:: invocation, so that re-exec would be a console flash every time the
:: installed app runs -- not just a dev-environment quirk. A stdlib venv's
:: launcher binaries don't do this, so the installed copy gets its own venv
:: built with the stdlib venv module instead of being a copy of the dev one.
:: The base interpreter for that venv is a vendored standalone Python under
:: runtime\ (excluded above, built by tools\vendor_runtime.bat) rather than
:: one resolved via uv at install time -- the target machine needs neither
:: uv nor a pre-installed Python. See docs/distribution-plan.md.
echo Building installed venv...

set "BASE_PYTHON=%SOURCE%\runtime\python.exe"
if not exist "%BASE_PYTHON%" (
    echo ERROR: bundled runtime not found at "%BASE_PYTHON%".
    echo This distribution wasn't packaged correctly -- see tools\vendor_runtime.bat.
    pause
    exit /b 1
)

if exist "%DEST%\.venv" (
    echo Removing previous installed venv...
    rd /s /q "%DEST%\.venv"
)

echo Using base interpreter: %BASE_PYTHON%

"%BASE_PYTHON%" -m venv "%DEST%\.venv"
if errorlevel 1 (
    echo ERROR: stdlib venv creation failed.
    pause
    exit /b 1
)

"%DEST%\.venv\Scripts\python.exe" -m pip install -r "%SOURCE%\requirements.txt"
if errorlevel 1 (
    echo ERROR: dependency install into the installed venv failed.
    pause
    exit /b 1
)

echo Installed venv ready at "%DEST%\.venv"

set "REMOVE_SOURCE=0"
set /p REMOVE_SOURCE_DIAL=Do you want to delete the installation files? (Y/N):
if /i "%REMOVE_SOURCE_DIAL%" == "Y" set "REMOVE_SOURCE=1"
if /i "%REMOVE_SOURCE_DIAL%" == "Yes" set "REMOVE_SOURCE=1"

set /p ANSWER=Do you want to continue to installation? (Y/N):
if /i "%ANSWER%" == "Y" goto :YES
if /i "%ANSWER%" == "Yes" goto :YES
goto :NO

:YES
echo confirmed
if "%REMOVE_SOURCE%" == "1"(
    call "%DEST%\src\installation.bat" "%SOURCE%"
) else (
    call "%DEST%\src\installation.bat"
)
echo completed
pause 

:NO