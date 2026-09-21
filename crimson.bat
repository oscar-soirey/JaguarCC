@echo off
setlocal
python "%~dp0crimson.py" %*
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%
