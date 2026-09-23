@echo off
chcp 65001 >nul
title BusForge 启动器
cd /d "%~dp0"

rem ===== 定位装有 PySide6 的 Python (优先 3.11) =====
set "PYEXE=%LocalAppData%\Programs\Python\Python311\python.exe"

if not exist "%PYEXE%" (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYEXE=py -3.11"
    ) else (
        set "PYEXE=python"
    )
)

rem ===== 校验 PySide6, 缺失则自动补装依赖 =====
%PYEXE% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo [提示] 当前 Python 缺少依赖, 正在自动安装 requirements.txt ...
    %PYEXE% -m pip install -r requirements.txt
    %PYEXE% -c "import PySide6" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败, 请检查网络后重试, 或手动执行:
        echo        %PYEXE% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo [启动] BusForge ...
%PYEXE% main.py
if errorlevel 1 (
    echo.
    echo [异常退出] 请将上方错误信息截图反馈
    pause
)
