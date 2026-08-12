@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Насосолинго — остановка

echo.
echo   Останавливаю базу данных...
docker compose down
echo.
echo   Готово. Данные сохранены.
echo   Чтобы стереть базу начисто: docker compose down -v
echo.
pause
