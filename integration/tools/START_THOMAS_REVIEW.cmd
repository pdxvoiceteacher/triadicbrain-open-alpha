@echo off
setlocal
set "TASK_ROOT=%~1"
if "%TASK_ROOT%"=="" set "TASK_ROOT=%~dp0..\..\..\10_PRODUCT_TASK_01"
python "%~dp0launch_totality_human_comparison.py" --task-root "%TASK_ROOT%"
exit /b %ERRORLEVEL%
