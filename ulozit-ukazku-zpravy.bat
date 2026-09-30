@echo off
rem Ulozi posledni vydanou zpravu od AI (z vymyslenych ukazkovych dat)
rem do repozitare, aby se ukazala i na PythonAnywhere.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || goto chyba

git pull || goto chyba
python manage.py ulozit_ukazku_zpravy %1 || goto chyba

git config user.name >nul || git config user.name "%USERNAME%"
git config user.email >nul || git config user.email "%USERNAME%@%COMPUTERNAME%.local"

git add demo\ukazkove_zpravy
git diff --cached --quiet && (
  echo Tato zprava uz ulozena je.
  pause
  exit /b 0
)
git commit -m "Ukazkova zprava od AI z %COMPUTERNAME%" || goto chyba
git push || goto chyba

echo.
echo Ulozeno. Na PythonAnywhere ji nactete aktualizaci (git pull a pa-update.sh).
pause
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
