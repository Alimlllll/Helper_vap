@echo off
chcp 65001 >nul
setlocal
:: =============================================================================
:: Сборка базы подсказок (часть автора, в репозиторий не попадает).
::
:: Свой venv в папке builder (numpy, scikit-learn - пользователям они не нужны).
:: Читает builder\data\checks\*.json, пишет ..\base\hints.db приложения.
::
:: Аргументы передаются в precompute.py:
::   build.bat --llm qwen2.5:7b
::   build.bat --llm qwen2.5:7b --emb intfloat/multilingual-e5-base
:: =============================================================================

set "TOOLBOX_HOME=%~dp0"
set "TOOLBOX_HOME=%TOOLBOX_HOME:~0,-1%"

if not exist "%TOOLBOX_HOME%\launchers\run_app.bat" (
    echo ERROR: launchers\run_app.bat not found next to %~nx0
    pause
    exit /b 1
)

set "TOOLBOX_APP_DIR=%TOOLBOX_HOME%"
set "TOOLBOX_APP_TITLE=Validation helper - build"
set "TOOLBOX_REQUIREMENTS=%TOOLBOX_HOME%\requirements.txt"
set "TOOLBOX_PY_MIN=3.10"

call "%TOOLBOX_HOME%\launchers\run_app.bat" precompute.py %*
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="0" pause
exit /b %CODE%
