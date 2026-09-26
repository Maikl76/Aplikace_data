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
rem Doplni do katalogu nove metriky a protokoly; vase upravy neprepise.
python manage.py seed_catalog --jen-chybejici || goto chyba
python manage.py prepocitat_odvozene || goto chyba

echo.
if /i "%~1"=="sit" goto sit
echo Aplikace bezi na http://localhost:8000  (ukonceni: Ctrl+C)
start "" http://localhost:8000
python manage.py runserver
exit /b 0

:sit
rem Pristup z tabletu a telefonu v mistni siti (jen pro sit laboratore!).
echo Aplikace bezi i pro tablety a telefony v teto siti.
echo Na tabletu otevrete adresu http://ADRESA-POCITACE:8000  - adresa je radek IPv4:
ipconfig | findstr /c:"IPv4"
echo Kdyz se Windows zepta na branu firewall, povolte jen soukromou sit.
start "" http://localhost:8000
python manage.py runserver 0.0.0.0:8000
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
