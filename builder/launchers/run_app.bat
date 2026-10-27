@echo off
chcp 65001 >nul
setlocal
:: =============================================================================
:: Универсальный запуск Python-приложения (Toolbox ARM).
::
::   run_app.bat [точка_входа] [аргументы приложения...]
::
:: Точка входа:
::   app.py, src\app.py, src/app.py  - запустить файл (путь от папки приложения)
::   main, package.cli               - запустить модуль: python -m <имя>
::   не указана                      - python -m main (как раньше)
::
:: Переменные, которые подставляет Toolbox ARM (при ручном запуске не нужны):
::   TOOLBOX_APP_DIR       папка приложения (иначе - текущая папка)
::   TOOLBOX_APP_TITLE     заголовок окна
::   TOOLBOX_ENTRY         точка входа, если она не передана первым аргументом
::   TOOLBOX_REQUIREMENTS  путь к requirements.txt из манифеста
::   TOOLBOX_PY_MIN        минимальная версия Python, например 3.10 (иначе 3.8)
:: =============================================================================

:: =============================================================================
:: Параметры запуска
:: =============================================================================
set "ENTRY=%~1"
if not defined ENTRY if defined TOOLBOX_ENTRY set "ENTRY=%TOOLBOX_ENTRY%"
if not defined ENTRY set "ENTRY=main"

:: Всё после точки входа - аргументы самого приложения.
set "APP_ARGS="
:collect_args
shift
if "%~1"=="" goto :args_done
set APP_ARGS=%APP_ARGS% "%~1"
goto :collect_args
:args_done

set "APP_TITLE=ExcelPanel"
if defined TOOLBOX_APP_TITLE set "APP_TITLE=%TOOLBOX_APP_TITLE%"
TITLE %APP_TITLE%

:: =============================================================================
:: Папка приложения и кириллица в путях
:: =============================================================================
set "APP_DIR=%CD%"
if defined TOOLBOX_APP_DIR set "APP_DIR=%TOOLBOX_APP_DIR%"
cd /d "%APP_DIR%"
if errorlevel 1 (
    echo ERROR: application folder not found: "%APP_DIR%"
    goto :wait_and_exit
)
for %%I in (.) do set "SCRIPT_DIR=%%~sI"
set "VENV_DIR=%SCRIPT_DIR%\venv"

:: Python пишет в файлы и в консоль в UTF-8 - как и сама консоль (chcp 65001).
set "PYTHONUTF8=1"

:: =============================================================================
:: Инициализация переменных
:: =============================================================================
if not defined PYTHON (set PYTHON=python)

set "MIN_MAJOR=3"
set "MIN_MINOR=8"
if defined TOOLBOX_PY_MIN (
    for /f "tokens=1,2 delims=." %%a in ("%TOOLBOX_PY_MIN%") do (
        set "MIN_MAJOR=%%a"
        set "MIN_MINOR=%%b"
    )
)
if not defined MIN_MINOR set "MIN_MINOR=0"

:: Создаем временную директорию
mkdir tmp 2>NUL
echo ###############################
echo %APP_TITLE%
echo ###############################
echo.
echo Application folder: "%APP_DIR%"
echo Entry point: %ENTRY%
echo.

:: =============================================================================
:: Блок 1: Поиск подходящей версии Python
:: =============================================================================
echo Searching for Python %MIN_MAJOR%.%MIN_MINOR% or higher...

set LATEST_PYTHON=
set LATEST_VERSION=0

:: Python 3.14
call :check_python_version "C:\Program Files\Python31414\python.exe"
call :check_python_version "C:\Program Files\Python314\python.exe"
:: Python 3.13
call :check_python_version "C:\Program Files\Python31313\python.exe"
call :check_python_version "C:\Program Files\Python313\python.exe"
:: Python 3.12
call :check_python_version "C:\Program Files\Python31212\python.exe"
call :check_python_version "C:\Program Files\Python312\python.exe"
:: Python 3.11
call :check_python_version "C:\Program Files\Python31111\python.exe"
call :check_python_version "C:\Program Files\Python311\python.exe"
:: Python 3.10
call :check_python_version "C:\Program Files\Python31010\python.exe"
call :check_python_version "C:\Program Files\Python310\python.exe"
:: Python 3.9
call :check_python_version "C:\Program Files\Python3919\python.exe"
call :check_python_version "C:\Program Files\Python39\python.exe"
:: Python 3.8
call :check_python_version "C:\Program Files\Python388\python.exe"
call :check_python_version "C:\Program Files\Python38\python.exe"

:: Пользовательская директория
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python31414\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python314\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python31313\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python31212\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python31111\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python31010\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python39\python.exe"
call :check_python_version "%USERPROFILE%\AppData\Local\Programs\Python\Python38\python.exe"

:: Anaconda
call :check_python_version "C:\Anaconda3\python.exe"
call :check_python_version "C:\Program Files\Anaconda3\python.exe"
call :check_python_version "C:\Program Files (x86)\Anaconda3\python.exe"
call :check_python_version "C:\ProgramData\Anaconda3\python.exe"

:: Поиск Python в PATH (в последнюю очередь)
call :check_python_in_path

if defined LATEST_PYTHON (
    set "PYTHON=%LATEST_PYTHON%"
    goto :python_found
)

echo ERROR: Python %MIN_MAJOR%.%MIN_MINOR% or higher not found
echo.
echo Please install Python %MIN_MAJOR%.%MIN_MINOR% or higher and try again.
goto :wait_and_exit

:python_found
echo Using Python: "%PYTHON%"
goto :setup_venv

:: =============================================================================
:: Функция поиска Python в PATH
:: =============================================================================
:check_python_in_path
for /f "delims=" %%i in ('where python 2^>nul') do (
    call :check_python_version "%%i"
)
goto :eof

:: =============================================================================
:: Функция проверки версии Python по указанному пути
:: =============================================================================
:check_python_version
set "PYTHON_PATH=%~1"
if not exist "%PYTHON_PATH%" goto :eof

"%PYTHON_PATH%" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" >tmp\version.txt 2>nul
if %ERRORLEVEL% neq 0 goto :eof

set "VERSION="
set /p VERSION=<tmp\version.txt
if not defined VERSION goto :eof

for /f "tokens=1,2 delims=." %%a in ("%VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

:: Пропускаем версии ниже минимальной
if %MAJOR% lss %MIN_MAJOR% goto :eof
if %MAJOR% equ %MIN_MAJOR% if %MINOR% lss %MIN_MINOR% goto :eof

for /f "tokens=1,2,3 delims=." %%a in ("%VERSION%") do (
    set /a VERSION_NUM=%%a * 10000 + %%b * 100 + %%c
)

if %VERSION_NUM% gtr %LATEST_VERSION% (
    set LATEST_VERSION=%VERSION_NUM%
    set "LATEST_PYTHON=%PYTHON_PATH%"
    echo Found Python %VERSION% at "%PYTHON_PATH%"
)
goto :eof

:: =============================================================================
:: Блок 2: Настройка виртуального окружения
:: =============================================================================
:setup_venv
echo.
echo Setting up virtual environment...
echo Virtual environment directory: %VENV_DIR%

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo Virtual environment already exists
    goto :activate_venv
)

echo Creating new virtual environment...
if exist "%VENV_DIR%" (
    echo Removing old virtual environment...
    rmdir /s /q "%VENV_DIR%" 2>nul
)

echo Using Python: "%PYTHON%"
"%PYTHON%" --version

echo Attempting to create virtual environment...
"%PYTHON%" -m venv "%VENV_DIR%" >tmp\venv_create.log 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to create virtual environment
    echo.
    echo Details from log:
    type tmp\venv_create.log
    echo.
    goto :wait_and_exit
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment was not created properly
    goto :wait_and_exit
)

echo Virtual environment created successfully

:activate_venv
for %%I in ("%VENV_DIR%") do set "SHORT_VENV_DIR=%%~sI"
set "VENV_PYTHON=%SHORT_VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%SHORT_VENV_DIR%\Scripts\pip.exe"

echo Virtual environment activated: %VENV_PYTHON%

:: =============================================================================
:: Блок 2.5: Интеграция tkinter из системного Python
:: =============================================================================
call :setup_tkinter

:: =============================================================================
:: Блок 3: Поиск requirements.txt и установка зависимостей
:: =============================================================================
echo.
echo Checking dependencies...

:: Порядок поиска:
::   1) путь из манифеста (TOOLBOX_REQUIREMENTS);
::   2) requirements.txt в корне папки приложения;
::   3) requirements.txt в подкаталогах - ближайший к корню. Папки venv, .venv,
::      .git, node_modules, __pycache__, tmp и site-packages пропускаются,
::      чтобы не подхватить requirements чужой библиотеки.
set "REQ_FILE="
if defined TOOLBOX_REQUIREMENTS if exist "%TOOLBOX_REQUIREMENTS%" set "REQ_FILE=%TOOLBOX_REQUIREMENTS%"
if defined TOOLBOX_REQUIREMENTS if not defined REQ_FILE echo WARNING: "%TOOLBOX_REQUIREMENTS%" not found, searching for requirements.txt...
if not defined REQ_FILE if exist "requirements.txt" set "REQ_FILE=requirements.txt"
if not defined REQ_FILE call :find_requirements

if not defined REQ_FILE (
    echo WARNING: requirements.txt not found, skipping dependency installation
    goto :launch_app
)

for %%I in ("%REQ_FILE%") do (
    set "REQ_FULL=%%~fI"
    set "REQ_DIR=%%~dpI"
    set "REQ_NAME=%%~nxI"
)
echo Requirements: "%REQ_FULL%"

:: Зависимости ставятся заново, только если requirements.txt изменился с
:: прошлой успешной установки: иначе каждый запуск ждал бы pip.
set "REQ_MARK=%VENV_DIR%\requirements.installed"
if exist "%REQ_MARK%" (
    fc /b "%REQ_FULL%" "%REQ_MARK%" >nul 2>&1
    if not errorlevel 1 (
        echo Dependencies are up to date
        goto :launch_app
    )
)

echo Installing dependencies from %REQ_NAME%...
if not exist "%REQ_MARK%" "%VENV_PYTHON%" -m pip install --upgrade pip

:: pip запускается из папки с requirements.txt: так строки вида "-r base.txt"
:: и "-e ." внутри файла указывают туда, куда задумал автор.
pushd "%REQ_DIR%"
"%VENV_PYTHON%" -m pip install -r "%REQ_NAME%" --progress-bar on
set PIP_EXIT_CODE=%ERRORLEVEL%
popd
if %PIP_EXIT_CODE% neq 0 (
    echo Failed to install dependencies
    goto :wait_and_exit
)

copy /Y "%REQ_FULL%" "%REQ_MARK%" >nul 2>&1
echo Dependencies installed successfully
goto :launch_app

:: =============================================================================
:: Функция поиска requirements.txt в подкаталогах (ближайший к корню)
:: =============================================================================
:find_requirements
"%VENV_PYTHON%" -c "import os;s={'venv','.venv','env','.git','node_modules','__pycache__','tmp','site-packages'};c=[os.path.join(r,'requirements.txt') for r,d,f in os.walk('.') if not d.__setitem__(slice(None),sorted(x for x in d if x not in s)) and 'requirements.txt' in f];print(min(c,key=lambda p:(p.count(os.sep),p)) if c else '')" >tmp\requirements_path.txt 2>nul
set /p REQ_FILE=<tmp\requirements_path.txt
if defined REQ_FILE echo Found requirements in subfolder: %REQ_FILE%
goto :eof

:: =============================================================================
:: Блок 4: Запуск приложения
:: =============================================================================
:launch_app
echo.
echo Starting application...
echo Application Python: %VENV_PYTHON%
"%VENV_PYTHON%" --version
echo.

:: Точка входа с расширением .py/.pyw - это файл, без расширения - модуль.
for %%I in ("%ENTRY%") do set "ENTRY_EXT=%%~xI"
if /i "%ENTRY_EXT%"==".py" goto :run_file
if /i "%ENTRY_EXT%"==".pyw" goto :run_file

echo Running module: %ENTRY%
"%VENV_PYTHON%" -m %ENTRY% %APP_ARGS%
set APP_EXIT_CODE=%ERRORLEVEL%
goto :after_run

:run_file
set "ENTRY=%ENTRY:/=\%"
if not exist "%ENTRY%" (
    echo ERROR: entry file not found: "%APP_DIR%\%ENTRY%"
    echo Check launch.target in the manifest.
    goto :wait_and_exit
)
for %%I in ("%ENTRY%") do set "ENTRY_SHORT=%%~sI"
echo Running file: %ENTRY%
"%VENV_PYTHON%" "%ENTRY_SHORT%" %APP_ARGS%
set APP_EXIT_CODE=%ERRORLEVEL%

:after_run
:: =============================================================================
:: Блок 5: Завершение работы
:: =============================================================================
if %APP_EXIT_CODE% equ 0 goto :success_exit
goto :error_exit

:success_exit
echo.
echo Program completed successfully
exit /b 0

:error_exit
echo.
echo ERROR: Application exited with error code %APP_EXIT_CODE%
echo Press any key to close this window...
pause >nul
exit /b %APP_EXIT_CODE%

:: =============================================================================
:: Универсальная точка выхода с ожиданием (для критических ошибок)
:: =============================================================================
:wait_and_exit
echo.
echo Press any key to close this window...
pause >nul
exit /b 1

:: =============================================================================
:: Функция: setup_tkinter - копирование Tcl/Tk в виртуальное окружение
:: =============================================================================
:setup_tkinter
echo.
echo Checking for tkinter in system Python...

for %%I in ("%PYTHON%") do set "SYS_PYTHON_DIR=%%~dpI"
set "SYS_PYTHON_DIR=%SYS_PYTHON_DIR:~0,-1%"
echo System Python directory: "%SYS_PYTHON_DIR%"

"%PYTHON%" -c "import tkinter" 2>nul
if %ERRORLEVEL% neq 0 (
    echo tkinter not found in system Python - skipping integration.
    goto :eof
)

:: tkinter в venv уже работает - копировать нечего
"%VENV_PYTHON%" -c "import tkinter" 2>nul
if %ERRORLEVEL% equ 0 (
    echo tkinter is available in virtual environment.
    goto :eof
)

set "TCL_SRC="
if exist "%SYS_PYTHON_DIR%\tcl" (
    set "TCL_SRC=%SYS_PYTHON_DIR%\tcl"
) else if exist "%SYS_PYTHON_DIR%\Lib\tcl" (
    set "TCL_SRC=%SYS_PYTHON_DIR%\Lib\tcl"
)

if not defined TCL_SRC (
    echo WARNING: Could not locate Tcl directory - tkinter may not work.
    goto :copy_dlls
)

echo Copying Tcl folder to virtual environment...
if exist "%VENV_DIR%\tcl" rmdir /s /q "%VENV_DIR%\tcl" 2>nul
xcopy "%TCL_SRC%" "%VENV_DIR%\tcl\" /E /I /Q /Y >nul
if %ERRORLEVEL% equ 0 (
    echo Tcl folder copied successfully.
) else (
    echo WARNING: Failed to copy Tcl folder.
)

:copy_dlls
set "DLL_SRC=%SYS_PYTHON_DIR%\DLLs"
if not exist "%DLL_SRC%" (
    echo DLLs folder not found - skipping DLL copy.
    goto :eof
)

echo Copying Tcl/Tk DLLs to virtual environment Scripts...
set "DLL_DEST=%VENV_DIR%\Scripts"
for %%F in (tcl86t.dll tk86t.dll) do (
    if exist "%DLL_SRC%\%%F" (
        copy /Y "%DLL_SRC%\%%F" "%DLL_DEST%\" >nul 2>&1 && echo   %%F copied.
    )
)

echo Verifying tkinter in venv...
"%VENV_PYTHON%" -c "import tkinter" 2>nul
if %ERRORLEVEL% equ 0 (
    echo tkinter successfully integrated into virtual environment.
) else (
    echo WARNING: tkinter still not importable in venv. Manual setup may be required.
)

goto :eof
