```bat
@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=WindowsPolicyDescriptionReader"
set "VENV_DIR=.venv"
set "PYTHON=py -3.11"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

echo ============================================================
echo BUILD %APP_NAME%
echo ============================================================
echo.

REM 1. Kiem tra Python 3.11
%PYTHON% --version
if errorlevel 1 (
    echo ERROR: Khong tim thay Python 3.11.
    echo Hay cai Python 3.11 x64 truoc khi build.
    pause
    exit /b 1
)

REM 2. Kiem tra cac tep can thiet
if not exist "main.py" (
    echo ERROR: Khong tim thay main.py
    pause
    exit /b 1
)

if not exist "policy_reader.py" (
    echo ERROR: Khong tim thay policy_reader.py
    pause
    exit /b 1
)

if not exist "requirements-build.txt" (
    echo ERROR: Khong tim thay requirements-build.txt
    pause
    exit /b 1
)

if not exist "data\description_translations_vi.json" (
    echo ERROR: Khong tim thay file JSON tu dien.
    pause
    exit /b 1
)

REM 3. Tao moi truong ao neu chua ton tai
if not exist "%VENV_PYTHON%" (
    echo.
    echo [1/5] Dang tao moi truong ao...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :failed
) else (
    echo.
    echo [1/5] Da tim thay moi truong ao.
)

REM 4. Nang cap pip va cai dat cong cu build
echo.
echo [2/5] Dang nang cap pip...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo.
echo [3/5] Dang cai dat requirements-build.txt...
"%VENV_PYTHON%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed

REM 5. Xoa ket qua build cu
echo.
echo [4/5] Dang don dep ket qua build cu...

if exist "build" rmdir /s /q "build"
if exist "dist\%APP_NAME%" rmdir /s /q "dist\%APP_NAME%"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

REM 6. Dong goi ONEDIR
echo.
echo [5/5] Dang dong goi chuong trinh...

"%VENV_PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name "%APP_NAME%" ^
    --add-data "data;data" ^
    main.py

if errorlevel 1 goto :failed

if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo ERROR: Khong tim thay file EXE.
    goto :failed
)

echo.
echo ============================================================
echo BUILD THANH CONG!
echo ============================================================
echo.
echo File chay:
echo dist\%APP_NAME%\%APP_NAME%.exe
echo.
echo Hay sao chep TOAN BO thu muc:
echo dist\%APP_NAME%
echo sang may tinh khac.
echo.
pause
exit /b 0

:failed
echo.
echo ============================================================
echo BUILD THAT BAI!
echo ============================================================
echo Hay kiem tra thong bao loi phia tren.
echo Moi truong ao duoc luu tai: %VENV_DIR%
echo.
pause
exit /b 1
```