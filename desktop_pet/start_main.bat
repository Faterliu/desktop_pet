@echo off
setlocal

cd /d "%~dp0"

if /i "%~1"=="--console" goto run_console

if exist "%SystemRoot%\System32\wscript.exe" (
    start "" "%SystemRoot%\System32\wscript.exe" "%~dp0start_main.vbs"
    exit /b 0
)

:run_console
set "RUNTIME_FILE=%~dp0data\runtime_python.txt"
set "PYTHON_EXE="

if exist "%RUNTIME_FILE%" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$text = [IO.File]::ReadAllText('%RUNTIME_FILE%'); $text = $text.Trim([char]0xFEFF, [char]13, [char]10, [char]9, [char]32); Write-Output $text" 2^>nul`) do (
        set "PYTHON_EXE=%%P"
    )
)

if not defined PYTHON_EXE (
    echo Runtime Python was not configured.
    echo Please run setup_env.bat first, then run start_main.bat again.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo Runtime Python was not found:
    echo %PYTHON_EXE%
    echo Please run setup_env.bat again.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import PySide6, requests" >nul 2>nul
if errorlevel 1 (
    echo Project dependencies are missing or incomplete.
    echo Please run setup_env.bat first, then run start_main.bat again.
    pause
    exit /b 1
)

"%PYTHON_EXE%" main.py
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
    exit /b 1
)

exit /b 0
