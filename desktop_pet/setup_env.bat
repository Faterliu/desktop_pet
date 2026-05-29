@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "DATA_DIR=%~dp0data"
set "RUNTIME_FILE=%DATA_DIR%\runtime_python.txt"
set "VENV_DIR=%~dp0.desktop_pet_venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP_TEMP_DIR=%~dp0.pip_tmp"
set "LEGACY_PIP_CACHE_DIR=%~dp0.pip_cache"
set "BASE_PYTHON="

set "PIP_NO_INDEX="
set "PIP_FIND_LINKS="
set "PIP_INDEX_URL="
set "PIP_EXTRA_INDEX_URL="
set "PIP_CONFIG_FILE="
set "PIP_NO_CACHE_DIR=1"
set "PIP_PROXY="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "NO_PROXY="

if not exist "%PIP_TEMP_DIR%" mkdir "%PIP_TEMP_DIR%"
set "TEMP=%PIP_TEMP_DIR%"
set "TMP=%PIP_TEMP_DIR%"

if not exist "requirements.txt" (
    echo requirements.txt was not found.
    pause
    exit /b 1
)

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

call :find_python

if not defined BASE_PYTHON (
    call :install_python
    if errorlevel 1 (
        pause
        exit /b 1
    )

    call :find_python
    if not defined BASE_PYTHON (
        echo Python was installed, but no usable Python command was found.
        echo Please run setup_env.bat again. If it still fails, reopen this terminal or restart Windows first.
        pause
        exit /b 1
    )
)

if not exist "!BASE_PYTHON!" (
    echo Resolved Python does not exist:
    echo !BASE_PYTHON!
    pause
    exit /b 1
)

"!BASE_PYTHON!" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo Resolved Python is not runnable:
    echo !BASE_PYTHON!
    pause
    exit /b 1
)

echo Using Python:
echo !BASE_PYTHON!
echo.

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import PySide6, requests" >nul 2>nul
    if errorlevel 1 (
        echo Existing virtual environment is missing project dependencies. Recreating it...
        rmdir /s /q "%VENV_DIR%" >nul 2>nul
        if exist "%VENV_DIR%" (
            echo Failed to remove existing virtual environment:
            echo %VENV_DIR%
            echo Please close programs that may be using it, delete this folder manually, then run setup_env.bat again.
            pause
            exit /b 1
        )
    )
)

if not exist "%VENV_PYTHON%" (
    if exist "%VENV_DIR%" (
        echo Existing virtual environment is incomplete. Recreating it...
        rmdir /s /q "%VENV_DIR%" >nul 2>nul
        if exist "%VENV_DIR%" (
            echo Failed to remove incomplete virtual environment:
            echo %VENV_DIR%
            echo Please close programs that may be using it, delete this folder manually, then run setup_env.bat again.
            pause
            exit /b 1
        )
    )

    echo Creating project virtual environment...
    "!BASE_PYTHON!" -m venv --system-site-packages --without-pip "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create the project virtual environment.
        echo No global Python packages were changed.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON%" (
    echo Project virtual environment was not created correctly:
    echo %VENV_PYTHON%
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import PySide6, requests" >nul 2>nul
if errorlevel 1 (
    echo Installing project dependencies into local virtual environment...
    "!BASE_PYTHON!" -m pip --python "%VENV_PYTHON%" install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies into the project virtual environment.
        echo No global Python packages were changed.
        pause
        exit /b 1
    )
)

"%VENV_PYTHON%" -c "import PySide6, requests" >nul 2>nul
if errorlevel 1 (
    echo Dependency verification failed.
    pause
    exit /b 1
)

if exist "%LEGACY_PIP_CACHE_DIR%" (
    echo Removing old local pip cache...
    rmdir /s /q "%LEGACY_PIP_CACHE_DIR%" >nul 2>nul
)

> "%RUNTIME_FILE%" <nul set /p "=%VENV_PYTHON%"

echo.
echo Environment is ready.
echo Runtime Python path was saved to:
echo %RUNTIME_FILE%
echo.
echo You can now run start_main.vbs.
pause
exit /b 0

:find_python
set "BASE_PYTHON="

call :accept_python "%USERPROFILE%\miniforge3\python.exe"
if defined BASE_PYTHON exit /b 0

for /f "delims=" %%P in ('powershell -NoProfile -Command "$root = Join-Path $env:APPDATA 'uv\python'; if (Test-Path $root) { Get-ChildItem $root -Recurse -Filter python.exe | Where-Object { $_.FullName -match 'cpython-3\.13' } | Select-Object -First 1 -ExpandProperty FullName }" 2^>nul') do (
    call :accept_python "%%P"
)
if defined BASE_PYTHON exit /b 0

for /f "delims=" %%P in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do (
    call :accept_python "%%P"
)
if defined BASE_PYTHON exit /b 0

for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    call :accept_python "%%P"
)
if defined BASE_PYTHON exit /b 0

for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    call :accept_python "%%P"
)
if defined BASE_PYTHON exit /b 0

exit /b 1

:accept_python
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1

"%~1" -c "import sys" >nul 2>nul
if errorlevel 1 exit /b 1

"%~1" -m pip --version >nul 2>nul
if errorlevel 1 exit /b 1

"%~1" -c "import venv" >nul 2>nul
if errorlevel 1 exit /b 1

"%~1" -m pip --help | findstr /C:"--python" >nul 2>nul
if errorlevel 1 exit /b 1

set "BASE_PYTHON=%~1"
exit /b 0

:install_python
where winget >nul 2>nul
if errorlevel 1 (
    echo No usable Python was found, and winget is not available.
    echo Please install Python 3.13 manually, then run setup_env.bat again.
    exit /b 1
)

echo No usable Python was found.
echo Installing Python 3.13 with winget...
winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Python installation failed.
    exit /b 1
)

exit /b 0
