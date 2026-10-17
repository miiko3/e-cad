@echo off
chcp 65001 >nul
title e-cad - САПР топологии печатных плат
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден. Установите Python 3.10+ и повторите.
    pause
    exit /b 1
)

python -c "import PySide6, numpy" >nul 2>nul
if errorlevel 1 (
    echo Устанавливаю зависимости PySide6 и numpy...
    python -m pip install PySide6 numpy
)

python main.py %*
if errorlevel 1 pause