@echo off
rem Ulozi posledni vydanou zpravu od AI (z vymyslenych ukazkovych dat)
rem do repozitare, aby se ukazala i na PythonAnywhere.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || goto chyba

rem Pojistka pred pull
rem Mistni zmeny v souborech aplikace (treba po pokusu o nasazeni nebo uprave
rem v editoru) by aktualizaci zastavily. Odlozi se stranou do git stash - nic
rem se nesmaze, vratit jdou prikazem: git stash pop
rem Radky az po git pull vcetne uz nemente: cmd cte tento soubor prubezne
rem a git pull ho muze prepsat za behu (hlida tests/test_bat.py).
git diff --quiet HEAD -- || (
  echo V souborech aplikace jsou mistni zmeny, odkladam je stranou:
  git status --short --untracked-files=no
  git -c user.name=aplikace -c user.email=aplikace@localhost stash push -m "mistni zmeny pred aktualizaci" || goto chyba
  echo Zmeny jsou odlozene, vratit je jde prikazem: git stash pop
)
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
