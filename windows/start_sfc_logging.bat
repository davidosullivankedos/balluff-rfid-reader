@echo off
rem Starts logging tag reads. Double-click to run; close the window or press Ctrl+C to stop.
rem
rem Set COM_PORT to the reader's port (run list_com_ports.bat, or look in
rem Device Manager > Ports (COM & LPT) for "Prolific" / "USB-Serial").
set COM_PORT=COM3
rem Log file: one line per read, "date time<TAB>tag data as hex".
rem The folder is created automatically if it doesn't exist.
set LOG_FILE=C:\balluff\sfc_log.txt

cd /d "%~dp0"
title Balluff tag logger - %COM_PORT%
bisc600.exe --port %COM_PORT% sfc --file "%LOG_FILE%"
echo.
echo Logger stopped.
pause
