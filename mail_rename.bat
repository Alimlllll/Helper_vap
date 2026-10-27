@echo off
chcp 65001 >nul
setlocal
:: =============================================================================
:: Переименование файлов для отправки почтой.
::
:: Почта не пропускает вложения .js и .bat, поэтому перед отправкой к ним
:: дописывается ".txt", а после получения - убирается.
::
::   mail_rename.bat          - сам решает: если есть файлы без .txt - добавит,
::                              иначе уберёт
::   mail_rename.bat add      - добавить ".txt"
::   mail_rename.bat remove   - убрать ".txt"
::
:: При «add» последним переименовывается и сам этот батник (mail_rename.bat.txt).
:: Получив письмо, уберите ".txt" у него вручную, затем запустите - он вернёт
:: остальные файлы (режим «remove» сам себя не трогает: он уже .bat).
:: Батник должен лежать в корне проекта «Помощник валидации проверок» (рядом со start.bat).
:: =============================================================================
cd /d "%~dp0"

set FILES="start.bat" "launchers\run_app.bat"

set "MODE=%~1"
if /i "%MODE%"=="add" goto :run
if /i "%MODE%"=="remove" goto :run
set "MODE=remove"
for %%F in (%FILES%) do if exist "%%~F" set "MODE=add"

:run
if /i "%MODE%"=="add" (
    echo Adding .txt to file names...
) else (
    echo Removing .txt from file names...
)
echo.

set "CHANGED=0"
set "MISSING=0"
for %%F in (%FILES%) do call :process "%%~F"

echo.
echo Renamed: %CHANGED%
if not "%MISSING%"=="0" echo Not found: %MISSING%
echo.
if /i "%MODE%"=="add" goto :self_rename
pause
exit /b 0

:: -----------------------------------------------------------------------------
:: Сам батник - последним. Пока он выполняется, cmd читает его с диска, поэтому
:: обычный ren оборвал бы работу. "(goto) 2>nul" сначала завершает батник,
:: а ren в той же строке выполняется уже после - так переименовать себя можно.
:: -----------------------------------------------------------------------------
:self_rename
if exist "%~f0.txt" (
    echo   SKIP: "%~nx0.txt" already exists - this file is not renamed
    echo.
    pause
    exit /b 0
)
echo   %~nx0  -^>  %~nx0.txt  ^(this file^)
echo.
pause
(goto) 2>nul & ren "%~f0" "%~nx0.txt"

:: -----------------------------------------------------------------------------
:: Один файл: %1 - путь без ".txt"
:: -----------------------------------------------------------------------------
:process
set "FILE=%~1"
set "NAME=%~nx1"
if /i "%MODE%"=="add" goto :process_add

:process_remove
if not exist "%FILE%.txt" (
    if exist "%FILE%" (echo   already without .txt: %FILE%) else (echo   NOT FOUND: %FILE%.txt& set /a MISSING+=1)
    goto :eof
)
if exist "%FILE%" (
    echo   SKIP: both "%FILE%" and "%FILE%.txt" exist - remove one of them
    goto :eof
)
ren "%FILE%.txt" "%NAME%"
if errorlevel 1 (echo   ERROR: could not rename %FILE%.txt) else (echo   %FILE%.txt  -^>  %NAME%& set /a CHANGED+=1)
goto :eof

:process_add
if not exist "%FILE%" (
    if exist "%FILE%.txt" (echo   already with .txt: %FILE%.txt) else (echo   NOT FOUND: %FILE%& set /a MISSING+=1)
    goto :eof
)
if exist "%FILE%.txt" (
    echo   SKIP: both "%FILE%" and "%FILE%.txt" exist - remove one of them
    goto :eof
)
ren "%FILE%" "%NAME%.txt"
if errorlevel 1 (echo   ERROR: could not rename %FILE%) else (echo   %FILE%  -^>  %NAME%.txt& set /a CHANGED+=1)
goto :eof
