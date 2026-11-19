@echo off
setlocal
pushd "%~dp0"
if not exist "dzen_stage_a2.py" goto missing_files
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -c "import sys, tkinter; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install

:python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys, tkinter; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto missing
python -m venv .venv
if errorlevel 1 goto failed

:install
".venv\Scripts\python.exe" -c "from importlib.metadata import version; assert version('playwright') == '1.62.0'" >nul 2>nul
if not errorlevel 1 goto run
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" -X utf8 dzen_stage_a2.py
if errorlevel 1 goto failed
popd
exit /b 0

:missing
echo Install Python 3.11 or newer from https://www.python.org/downloads/windows/
echo Keep Tcl/Tk enabled and use Add Python to PATH in the installer.
goto failed

:missing_files
echo Extract all files from Dzen-A2-Windows.zip before starting.
goto failed

:failed
echo Dzen A.2 failed to start. See START.txt for setup instructions.
popd
pause
exit /b 1
