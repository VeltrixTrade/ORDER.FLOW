@echo off
chcp 65001 > nul
title 🥇 Gold Analysis Bot - تشغيل البوت
echo ===================================================
echo 🥇 جاري تشغيل بوت تحليل الذهب بالذكاء الاصطناعي...
echo 🥇 Starting XAU/USD AI Trading Analyst Bot...
echo ===================================================
echo.
cd /d "%~dp0"
python bot.py
if %errorlevel% neq 0 (
    echo.
    echo ❌ حدث خطأ أثناء تشغيل البوت!
    echo ❌ An error occurred while running the bot!
    echo.
    pause
)
