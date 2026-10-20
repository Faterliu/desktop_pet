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

rem Keep this file ASCII-only: cmd.exe decodes .bat in the OEM code page, so UTF-8
rem Chinese comments can be mangled into commands here.
rem Install source order: DESKTOP_PET_PIP_INDEX (optional) -> default PyPI -> bundled mirrors.
rem Every source gets a short timeout so a stalled default index falls back quickly.
set "PIP_INSTALL_OPTS=--timeout 15 --retries 1 --disable-pip-version-check"
set "PIP_FALLBACK_INDEXES=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple"

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
    rem Only check that the interpreter runs; missing packages are handled further down.
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Existing virtual environment cannot run Python. Recreating it...
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

echo Checking project dependencies against requirements.txt...
call :dependencies_satisfied
if not errorlevel 1 goto :deps_ready

rem Keep this flow flat on purpose: exit /b inside nested parentheses loses both the
rem remaining block and the exit code, so failures leave via goto to a top-level label.
set "INSTALL_OK="
if defined DESKTOP_PET_PIP_INDEX call :install_requirements "!DESKTOP_PET_PIP_INDEX!"
if not defined INSTALL_OK call :install_requirements ""
if not defined INSTALL_OK for %%M in (%PIP_FALLBACK_INDEXES%) do if not defined INSTALL_OK call :install_requirements "%%M"
if not defined INSTALL_OK goto :install_failed

call :dependencies_satisfied
if errorlevel 1 goto :verify_failed

:deps_ready
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

:install_failed
echo Failed to install dependencies into the project virtual environment.
echo No global Python packages were changed.
echo Set DESKTOP_PET_PIP_INDEX to a reachable index URL and run setup_env.bat again.
pause
exit /b 1

:verify_failed
echo Dependency verification failed.
pause
exit /b 1

:install_requirements
rem Try the given source, then the default PyPI, then the bundled mirrors; stop at the first success.
set "INDEX_ARGS="
if not "%~1"=="" set "INDEX_ARGS=--index-url %~1"
if "%~1"=="" (echo Installing project dependencies from the default PyPI...) else (echo Installing project dependencies from %~1...)
"!BASE_PYTHON!" -m pip --python "%VENV_PYTHON%" install %INDEX_ARGS% %PIP_INSTALL_OPTS% -r "%~dp0requirements.txt"
if not errorlevel 1 set "INSTALL_OK=1"
goto :eof

:dependencies_satisfied
rem Resolve requirements.txt with pip itself against the installed versions: --no-index stays
rem local and never touches the network, --dry-run writes nothing. 0 means fully satisfied.
"!BASE_PYTHON!" -m pip --python "%VENV_PYTHON%" install --no-index --dry-run --quiet --disable-pip-version-check -r "%~dp0requirements.txt"
goto :eof

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
