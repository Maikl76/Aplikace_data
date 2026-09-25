@echo off
rem Jednorazove zalozeni aplikace na novem pocitaci (Windows).
rem Staci dvojklik. Muzete ho spustit i znovu - co uz existuje, preskoci.
cd /d "%~dp0"

where python >nul 2>nul || (
  echo Python neni nainstalovany. Stahnete ho z https://www.python.org/downloads/
  echo a pri instalaci zaskrtnete "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist .venv (
  echo Zakladam virtualni prostredi...
  python -m venv .venv || goto chyba
)
call .venv\Scripts\activate.bat || goto chyba

echo Instaluji knihovny (poprve to trva nekolik minut)...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements\dev.txt || goto chyba

if not exist .env (
  copy .env.lokalne.example .env >nul
  echo Vytvoren soubor .env se zakladnim nastavenim.
)

rem Klic k sifrovanym jmenum sportovcu (doplni se jen jednou).
python manage.py zajisti_klic || goto chyba

set NOVA_DATABAZE=0
if not exist db.sqlite3 set NOVA_DATABAZE=1

python manage.py migrate || goto chyba

if "%NOVA_DATABAZE%"=="1" (
  echo Vytvarim vymyslena ukazkova data...
  python manage.py seed_demo || goto chyba
)

if exist katalog\katalog.json (
  echo Nacitam katalog z repozitare...
  python manage.py import_katalog || goto chyba
)

echo.
echo Hotovo. Aplikaci spoustejte souborem spustit.bat
echo Prihlaseni: admin / demo-heslo-1234
pause
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
