@echo off
setlocal
title ViralCutter WebUI

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
	echo [ERROR] Virtual environment not found.
	echo Run install_dependencies.bat first.
	echo.
	pause
	exit /b 1
)

".venv\Scripts\python.exe" webui\app.py
echo.
pause
