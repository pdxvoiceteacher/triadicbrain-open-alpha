@echo off
setlocal
if "%~1"=="" (
  echo Usage: %~nx0 ^<new-external-output-directory^> 1>&2
  exit /b 2
)
python "%~dp0run_substantive_totality_task.py" --output-dir "%~1"
exit /b %ERRORLEVEL%
