
@echo off
setlocal
cd /d "%~dp0"

echo Dang khoi dong Windows Policy Description Reader...
echo.

py -3.11 main.py

if not errorlevel 1 goto end

python main.py

if errorlevel 1 (
    echo.
    echo Khong the khoi dong chuong trinh.
    echo Hay kiem tra Python va cac thu vien phu thuoc.
    pause
)

:end
