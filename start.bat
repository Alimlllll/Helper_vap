@echo off
chcp 65001 >nul
setlocal
:: =============================================================================
:: Помощник валидации проверок - запуск.
::
:: Работает через универсальный батник Toolbox ARM (launchers\run_app.bat):
:: найдёт Python 3.10+, создаст venv в этой папке, поставит зависимости из
:: requirements.txt (заново - только если файл изменился) и запустит run.py:
:: сервер с готовой базой base\hints.db и браузер. Сборка базы - builder\build.bat.
::
:: Аргументы передаются в run.py:  start.bat --port 9000 --no-browser
::                                 start.bat --host 0.0.0.0   (доступ из сети)
:: =============================================================================

set "TOOLBOX_HOME=%~dp0"
set "TOOLBOX_HOME=%TOOLBOX_HOME:~0,-1%"

if not exist "%TOOLBOX_HOME%\launchers\run_app.bat" (
    echo ERROR: launchers\run_app.bat not found next to %~nx0
    pause
    exit /b 1
)

set "TOOLBOX_APP_DIR=%TOOLBOX_HOME%"
set "TOOLBOX_APP_TITLE=Validation helper"
set "TOOLBOX_REQUIREMENTS=%TOOLBOX_HOME%\requirements.txt"
set "TOOLBOX_PY_MIN=3.10"

call "%TOOLBOX_HOME%\launchers\run_app.bat" run.py %*
exit /b %ERRORLEVEL%
