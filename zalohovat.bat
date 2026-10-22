@echo off
rem Zaloha laboratorniho pocitace: databaze, nahrane soubory a .env s klici.
rem Dvojklik = zaloha do slozky Zalohy-FTVS ve vasem profilu (C:\Users\jmeno).
rem   zalohovat.bat "E:\zalohy"   = zaloha jinam (flash disk, sitovy disk).
rem Bez .env (klice) jsou ulozena jmena sportovcu necitelna - proto se bere i on.
rem Slozku se zalohou ulozte mimo tento pocitac (sifrovany disk, sitove uloziste).
cd /d "%~dp0"

if not exist .venv (
  echo Aplikace tu jeste neni zalozena - spustte nejdriv zalozit.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat || goto chyba

if "%~1"=="" (
  python manage.py zalohovat || goto chyba
) else (
  python manage.py zalohovat --cil "%~1" || goto chyba
)
echo.
pause
exit /b 0

:chyba
echo.
echo Zaloha se nepovedla. Poslete snimek teto obrazovky.
pause
exit /b 1
