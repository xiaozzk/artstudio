@echo off
REM ============================================
REM  2D Preview Browser - one-click launcher (cmd)
REM
REM  Why ASCII-only: cmd reads .bat files in the system
REM  ANSI/OEM codepage, so non-ASCII (CJK) text inside the
REM  script can become garbled tokens and fail to parse.
REM  For full Chinese UX use start.ps1 instead.
REM
REM  Usage:
REM    Double-click this file, or:
REM    start.bat                          (open browser)
REM    start.bat --no-browser
REM    start.bat --port 9000
REM ============================================
pushd "%~dp0\..\.."

REM --- detect Python interpreter ---
where python >nul 2>&1
if not errorlevel 1 goto :run_py

where py >nul 2>&1
if not errorlevel 1 goto :run_py_launcher

REM --- Python missing ---
echo.
echo [ERROR] Python 3.7+ not found in PATH.
echo         Install from https://www.python.org/downloads/
echo.
popd
pause
exit /b 1

:run_py
echo.
echo ===  2D Preview Browser  ===
echo   python : python
echo   cwd    : %CD%
echo ===========================
echo.
python tools\preview-2d\serve.py %*
goto :after

:run_py_launcher
echo.
echo ===  2D Preview Browser  ===
echo   python : py
echo   cwd    : %CD%
echo ===========================
echo.
py tools\preview-2d\serve.py %*
goto :after

:after
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" pause
exit /b %RC%
