@echo off
rem Lists the serial ports on this PC. The reader's USB adapter shows as "Prolific" / "USB-Serial".
cd /d "%~dp0"
bisc600.exe ports
echo.
pause
