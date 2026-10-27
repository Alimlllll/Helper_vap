@echo off
chcp 65001 >nul
setlocal
:: Новая версия Помощника валидации: поднять номер в VERSION и дописать CHANGELOG.md.
:: Без аргументов спросит, что изменилось. Примеры аргументов:
::   bump_version.bat --minor            1.0.015 -> 1.1.001
::   bump_version.bat -c "Новая кнопка"  пункт истории сразу, без вопросов
::   bump_version.bat --dry-run          только показать
cd /d "%~dp0"
set "PYTHONUTF8=1"

:: Python из venv проекта (его создаёт start.bat), иначе системный.
set "PY=python"
if exist "%~dp0..\venv\Scripts\python.exe" set "PY=%~dp0..\venv\Scripts\python.exe"

"%PY%" "%~dp0bump_version.py" %*
echo.
pause
