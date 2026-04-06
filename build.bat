@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYTHON=C:\Users\zhang\miniconda3\envs\gxy\python.exe
set PYINSTALLER=C:\Users\zhang\miniconda3\envs\gxy\Scripts\pyinstaller.exe
set CONDA_BIN=C:\Users\zhang\miniconda3\envs\gxy\Library\bin
set APP_NAME=工学云自动批阅工具

echo ===================================================
echo   工学云自动批阅工具 - PyInstaller 打包脚本
echo ===================================================
echo.

REM 检查 PyInstaller 是否已安装
if not exist "%PYINSTALLER%" (
    echo [安装] PyInstaller 未找到，正在安装...
    "%PYTHON%" -m pip install pyinstaller -q
)

REM 将 conda Library\bin 加入 PATH，确保 ffi.dll 等系统 DLL 被自动收集
set PATH=%CONDA_BIN%;%PATH%

echo [打包] 正在打包，请稍候...
"%PYINSTALLER%" ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "%APP_NAME%" ^
    --collect-all customtkinter ^
    --collect-data darkdetect ^
    --hidden-import apscheduler.triggers.cron ^
    --hidden-import apscheduler.triggers.date ^
    --hidden-import apscheduler.triggers.interval ^
    --hidden-import apscheduler.executors.pool ^
    --hidden-import apscheduler.executors.base ^
    --hidden-import apscheduler.jobstores.base ^
    --hidden-import apscheduler.jobstores.memory ^
    app.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo ===================================================
echo   打包完成！输出目录：dist\%APP_NAME%\
echo.
echo   注意：首次运行 exe 会自动创建 config.yaml，
echo         请在其中填写账号信息后重启工具。
echo ===================================================
pause
