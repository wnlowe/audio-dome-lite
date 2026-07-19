@echo off
setlocal EnableDelayedExpansion

set "SOURCE=%~dp0"
if "%SOURCE:~-1%"=="\" set "SOURCE=%SOURCE:~0,-1%"
set "APPNAME=audio-dome-lite"
set "DEST=%LOCALAPPDATA%\%APPNAME%"

if not exist "%DEST%" (
    mkdir "%DEST%"
)

set "EX_DIR=.git"
set "EX_FILES=.gitignore .python-version pyproject.toml uv.lock"

echo Moving files from "%SOURCE%" to "%DEST%"...
robocopy "%SOURCE%" "%DEST%" /E /NFL /NDL /NJH /NJS /XF "%~nx0" /XD %EX_DIR% /XF %EX_FILES%

:: robocopy exit codes: 0-7 = success (various), 8+ = failure
if %ERRORLEVEL% GEQ 8 (
    echo ERROR: robocopy failed with code %ERRORLEVEL%
    pause
    exit /b 1
)

echo Move complete. Files now in "%DEST%"

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