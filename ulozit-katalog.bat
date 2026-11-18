@echo off
rem Ulozi katalog (testy, metriky, MDC, normy, pravidla, clanky) do repozitare,
rem aby se dal nacist na druhem pocitaci nebo na serveru.
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
python manage.py export_katalog || goto chyba

rem Git potrebuje vedet, kdo zmenu udelal. Na novem pocitaci to jeste nevi.
git config user.name >nul || git config user.name "%USERNAME%"
git config user.email >nul || git config user.email "%USERNAME%@%COMPUTERNAME%.local"

git add katalog\katalog.json
git diff --cached --quiet && (
  echo Katalog se od posledniho ulozeni nezmenil.
  pause
  exit /b 0
)
git commit -m "Katalog: aktualizace z %COMPUTERNAME%" || goto chyba
git push || goto chyba

echo.
echo Katalog ulozen. Na druhem pocitaci spustte nacist-katalog.bat
pause
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
