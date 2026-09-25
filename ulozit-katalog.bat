@echo off
rem Ulozi katalog (testy, metriky, MDC, normy, pravidla, clanky) do repozitare,
rem aby se dal nacist na druhem pocitaci nebo na serveru.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || goto chyba

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
