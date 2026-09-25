@echo off
rem Nacte katalog ulozeny na jinem pocitaci (ulozit-katalog.bat).
rem POZOR: prepise zmeny v katalogu, ktere jste na TOMTO pocitaci neulozili.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || goto chyba

echo Nacteni prepise zmeny v katalogu, ktere jste na tomto pocitaci
echo jeste neulozili pres ulozit-katalog.bat.
choice /m "Pokracovat"
if errorlevel 2 exit /b 0

git pull || goto chyba
python manage.py import_katalog || goto chyba
pause
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
