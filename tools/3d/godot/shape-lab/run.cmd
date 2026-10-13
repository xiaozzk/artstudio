@echo off
rem =============================================================================
rem  artstudio shape-lab -- one-command Windows entry (Godot 4.6)
rem
rem    run.cmd             open the window: fixed-size offscreen stage + Chinese panel
rem    run.cmd --shots     render PNGs into tmp\shape-lab\shots\ (watchdog protected)
rem    run.cmd --fixtures  offline demo (in-memory stand-in characters, no morphs)
rem    run.cmd --selftest  interaction self-test (exit code 0 = all green)
rem
rem  Env: ARTSTUDIO_GODOT / ARTSTUDIO_BLENDER / ARTSTUDIO_SHAPELAB_CACHE
rem       ARTSTUDIO_SHAPELAB_TIMEOUT (watchdog seconds for --shots, default 900)
rem
rem  NOTE 1: this file is deliberately ASCII-only.  A UTF-8 .cmd with Chinese text
rem          gets merged/mangled by cmd.exe on a GBK console (a trailing lead byte
rem          eats the newline), which makes cmd execute garbage.  Chinese messages
rem          come from the Godot side (GDScript/UTF-8 safe) and from bake.py.
rem  NOTE 2: the watchdog is mandatory: when a GDScript fails to COMPILE, Godot
rem          spins forever and never quits, so we must kill it on timeout.
rem  NOTE 3: --shots is NOT headless.  Godot's dummy renderer cannot produce an
rem          image (ViewportTexture.get_image() returns null), so a small real
rem          window is opened instead; PNG sizes come from the fixed offscreen
rem          SubViewports (960x900 stage, 1500x900 page), never from the window.
rem  Zero asset copies: this project stores no .glb/.png; bake.py exports to
rem  tmp\shape-lab\ and Godot loads those .glb files by ABSOLUTE path at runtime.
rem =============================================================================
setlocal enabledelayedexpansion
title shape-lab
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
for %%I in ("%HERE%\..\..\..\..") do set "REPO=%%~fI"

rem ---- 1. locate Godot --------------------------------------------------------
set "GODOT="
if defined ARTSTUDIO_GODOT if exist "%ARTSTUDIO_GODOT%" set "GODOT=%ARTSTUDIO_GODOT%"
if not defined GODOT if exist "D:\godot\Godot_v4.6.2-stable_win64_console.exe" set "GODOT=D:\godot\Godot_v4.6.2-stable_win64_console.exe"
if not defined GODOT for %%I in (Godot_v4.6.2-stable_win64_console.exe) do if exist "%%~$PATH:I" set "GODOT=%%~$PATH:I"
if not defined GODOT for %%I in (godot.exe) do if exist "%%~$PATH:I" set "GODOT=%%~$PATH:I"
if not defined GODOT (
	echo [shape-lab] Godot not found. Point ARTSTUDIO_GODOT at the Godot 4.6 executable.
	echo [shape-lab] e.g.  set ARTSTUDIO_GODOT=D:\godot\Godot_v4.6.2-stable_win64_console.exe
	exit /b 2
)

rem ---- 2. cache: missing or stale vs source .blend  ->  call bake.py -----------
set "CACHE=%ARTSTUDIO_SHAPELAB_CACHE%"
if not defined CACHE set "CACHE=%REPO%\tmp\shape-lab"
set "TMPF=%TEMP%\shape_lab_stale_%RANDOM%.txt"
powershell -NoProfile -Command "$m=Get-Item -LiteralPath '%CACHE%\manifest.json' -EA SilentlyContinue; if($m){$n=Get-ChildItem -LiteralPath '%REPO%\assets\3d\rig' -Recurse -Filter *.blend -EA SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($n -and $n.LastWriteTime -gt $m.LastWriteTime){'1'}else{'0'}}else{'1'}" > "%TMPF%" 2>nul
set "STALE="
set /p STALE=<"%TMPF%"
del "%TMPF%" >nul 2>nul
if "%STALE%"=="1" goto bake
goto mode

:bake
if not exist "%HERE%\bake.py" (
	echo [shape-lab] cache missing/stale but bake.py is absent -^> use run.cmd --fixtures meanwhile.
	exit /b 3
)
set "BLENDER=%ARTSTUDIO_BLENDER%"
if not defined BLENDER if exist "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if not defined BLENDER (
	echo [shape-lab] Blender not found. Point ARTSTUDIO_BLENDER at blender.exe.
	exit /b 3
)
set "PY="
for %%I in (python.exe) do if exist "%%~$PATH:I" set "PY=%%~$PATH:I"
if not defined PY (
	echo [shape-lab] python not found on PATH; cannot call bake.py.
	exit /b 3
)
set "ARTSTUDIO_BLENDER=%BLENDER%"
echo [shape-lab] cache missing/stale -^> baking: bake.py --cache "%CACHE%"
pushd "%REPO%"
"%PY%" "%HERE%\bake.py" --cache "%CACHE%" --blender "%BLENDER%"
set "BAKE_RC=!ERRORLEVEL!"
popd
if not "!BAKE_RC!"=="0" (
	echo [shape-lab] bake.py failed, rc=!BAKE_RC!  logs: %CACHE%\logs\
	exit /b !BAKE_RC!
)

rem ---- 3. pick the mode -------------------------------------------------------
:mode
set "MODE=interactive"
echo %* | find /i "--shots" >nul && set "MODE=shots"
set "EXTRA="
echo %* | find /i "--fixtures" >nul && set "EXTRA=--fixtures"
echo %* | find /i "--selftest" >nul && set "EXTRA=--selftest"
if /i "%MODE%"=="shots" goto shots

:interactive
echo [shape-lab] opening window: LMB drag = orbit, wheel = zoom, right panel = k/h sliders and presets.
"%GODOT%" --path "%HERE%" --resolution 1500x900 -- %EXTRA%
exit /b %ERRORLEVEL%

rem ---- 4. shots mode: Start-Process + watchdog hard kill -----------------------
:shots
set "TIMEOUT_S=900"
if defined ARTSTUDIO_SHAPELAB_TIMEOUT set "TIMEOUT_S=%ARTSTUDIO_SHAPELAB_TIMEOUT%"
set "SHAPELAB_GODOT=%GODOT%"
set "SHAPELAB_PROJ=%HERE%"
set "SHAPELAB_EXTRA=%EXTRA%"
echo [shape-lab] shots mode: offscreen 960x900 stage + 1500x900 page; watchdog %TIMEOUT_S%s.
rem  Exit code must come from System.Diagnostics.Process: Start-Process -PassThru returns an
rem  EMPTY ExitCode for a long-running Godot here (verified), which would fake a green run.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$si=[System.Diagnostics.ProcessStartInfo]::new(); $si.FileName=$env:SHAPELAB_GODOT; $si.UseShellExecute=$false; $al='--path \"'+$env:SHAPELAB_PROJ+'\" --resolution 960x900 -- --shots'; if($env:SHAPELAB_EXTRA){$al=$al+' '+$env:SHAPELAB_EXTRA}; $si.Arguments=$al; $p=[System.Diagnostics.Process]::new(); $p.StartInfo=$si; $p.Start()|Out-Null; if(-not $p.WaitForExit([int]$env:TIMEOUT_S*1000)){ $p.Kill($true); Write-Host ('[shape-lab] WATCHDOG TIMEOUT {0}s - Godot killed (usually a script compile error spinning)' -f $env:TIMEOUT_S); exit 4 }; Write-Host ('[shape-lab] Godot exit code = '+$p.ExitCode); exit $p.ExitCode"
exit /b %ERRORLEVEL%
