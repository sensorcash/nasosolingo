@echo off
chcp 65001 >nul
rem Переходим в папку, где лежит батник — чтобы работало из любого места
cd /d "%~dp0"
title Насосолинго — сервер

echo.
echo   НАСОСОЛИНГО
echo   ================================
echo.

rem --- 1. Docker Desktop запущен? ---
docker info >nul 2>&1
if errorlevel 1 (
    echo   [!] Docker Desktop не запущен.
    echo.
    echo   Запустите Docker Desktop, дождитесь зелёного индикатора
    echo   в левом нижнем углу и попробуйте снова.
    echo.
    pause
    exit /b 1
)

rem --- 2. Поднимаем базу и Redis ---
echo   Запускаю базу данных...
docker compose up -d
if errorlevel 1 (
    echo.
    echo   [!] Не удалось запустить базу.
    echo   Возможно, порт 5432 или 6379 занят другой программой.
    echo.
    pause
    exit /b 1
)

rem --- 3. Окружение Python на месте? ---
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   [!] Не найдено окружение .venv
    echo.
    echo   Создайте его двумя командами:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem --- 4. Даём базе пару секунд проснуться ---
timeout /t 3 /nobreak >nul

rem --- Показываем адрес для телефона (сам определит нужный IP) ---
.venv\Scripts\python tools\show_url.py

echo   Swagger:             http://localhost:8000/docs
echo.
echo   Остановить — закройте окно или Ctrl+C
echo.

rem --- 5. Через 5 секунд откроем браузер. Не нужно — удалите строку ниже.
start "" /min cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8000/app"

rem --- 6. Запускаем сервер. Окно останется занятым — это нормально.
.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0

echo.
echo   Сервер остановлен.
pause
