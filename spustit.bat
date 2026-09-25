@echo off
rem Stahne nejnovejsi verzi, upravi databazi a spusti aplikaci.
rem Okno nechte otevrene - dokud bezi, bezi i aplikace. Ukonceni: Ctrl+C.
cd /d "%~dp0"

if not exist .venv (
  echo Aplikace tu jeste neni zalozena - spustte nejdriv zalozit.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat || goto chyba

echo Stahuji nejnovejsi verzi...
git pull || goto chyba

rem Kdyby pribyla nova knihovna. Kdyz nic nepribylo, trva to par sekund.
pip install --quiet -r requirements\dev.txt || goto chyba
python manage.py zajisti_klic || goto chyba
python manage.py migrate || goto chyba

echo.
echo Aplikace bezi na http://localhost:8000  (ukonceni: Ctrl+C)
start "" http://localhost:8000
python manage.py runserver
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
