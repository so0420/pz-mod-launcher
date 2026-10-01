@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m unittest discover -p "test_*.py" -q
if errorlevel 1 goto failed
".venv\Scripts\python.exe" build.py %*
if errorlevel 1 goto failed
echo.
echo Build complete. See the dist folder.
if "%~1"=="" pause
exit /b 0
:failed
echo.
echo Build failed. Python 3.11 or newer with Tcl/Tk is required.
pause
exit /b 1
