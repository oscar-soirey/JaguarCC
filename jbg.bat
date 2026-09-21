@echo off
setlocal
python "%~dp0jbg.py" %*
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%
