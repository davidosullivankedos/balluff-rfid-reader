@echo off
rem Build dist\bisc600.exe on a Windows PC.
rem Needs Python 3 from python.org (it installs the "py" launcher). Double-click to run.

cd /d "%~dp0\.."

echo === Creating build environment (.venv-win)
py -3 -m venv .venv-win || goto :error

echo === Installing pyserial and PyInstaller
.venv-win\Scripts\python -m pip install --upgrade pip || goto :error
.venv-win\Scripts\python -m pip install -r requirements.txt pyinstaller || goto :error

echo === Running tests
.venv-win\Scripts\python -m unittest || goto :error

echo === Building bisc600.exe
.venv-win\Scripts\python -m PyInstaller --onefile --console --clean --name bisc600 bisc600.py || goto :error

copy /y windows\start_sfc_logging.bat dist\ >nul || goto :error
copy /y windows\list_com_ports.bat dist\ >nul || goto :error
copy /y windows\README.md dist\README.md >nul || goto :error

echo.
echo === Done. Copy everything in the dist folder to the station PC:
dir /b dist
pause
exit /b 0

:error
echo.
echo *** BUILD FAILED - see the messages above ***
pause
exit /b 1
