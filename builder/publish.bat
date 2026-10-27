@echo off
chcp 65001 >nul
setlocal
:: =============================================================================
:: Выпуск новой базы для пользователей: сборка -> новая версия -> commit и push.
::
:: 1) собирает базу (как build.bat), 2) поднимает VERSION и пишет в CHANGELOG.md
:: «Обновлена база подсказок: N проверок», 3) по вашему подтверждению делает
:: git commit и push папки приложения. Пользователи получат базу кнопкой
:: «Обновить и перезапустить».
::
::   publish.bat                       обычный выпуск
::   publish.bat --llm qwen2.5:7b      аргументы сборки
::   publish.bat --no-build            база уже собрана
:: =============================================================================

set "TOOLBOX_HOME=%~dp0"
set "TOOLBOX_HOME=%TOOLBOX_HOME:~0,-1%"

if not exist "%TOOLBOX_HOME%\launchers\run_app.bat" (
    echo ERROR: launchers\run_app.bat not found next to %~nx0
    pause
    exit /b 1
)

set "TOOLBOX_APP_DIR=%TOOLBOX_HOME%"
set "TOOLBOX_APP_TITLE=Validation helper - publish"
set "TOOLBOX_REQUIREMENTS=%TOOLBOX_HOME%\requirements.txt"
set "TOOLBOX_PY_MIN=3.10"

call "%TOOLBOX_HOME%\launchers\run_app.bat" publish.py %*
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="0" pause
exit /b %CODE%
