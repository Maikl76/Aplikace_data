@echo off
rem Nacte studii PRODEF ze sesitu pro spoluautory (xlsx) do aplikace NA TOMTO POCITACI.
rem Pouziti: pretahnete sesit mysi na tento soubor, nebo ho spustte a zadejte cestu.
rem Data zustanou jen v databazi tohoto pocitace - do gitu ani na server se nenahravaji.
rem Zaheslovany sesit: na heslo se prikaz zepta (pri psani se nezobrazuje).
rem Nejdriv ukaze, co v sesitu nasel, a nacte az po potvrzeni ANO.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || goto chyba

set "SESIT=%~1"
if "%SESIT%"=="" set /p SESIT=Cesta k sesitu PRODEF (xlsx): 
if "%SESIT%"=="" goto chyba

python manage.py import_prodef "%SESIT%" --zeptat || goto chyba
echo.
echo V aplikaci: Tymovy prehled - PRODEF Stres / PRODEF Kontrola.
pause
exit /b 0

:chyba
echo.
echo Neco se nepovedlo. Poslete snimek teto obrazovky.
pause
exit /b 1
