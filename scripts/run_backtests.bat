@echo off
setlocal
cd /d "%~dp0.."
where conda >nul 2>nul || (echo Conda was not found on PATH. & exit /b 1)
call conda run -n lastdance python scripts\verify_environment.py || exit /b 1
call conda run -n lastdance python -m lastdance all --open %*
exit /b %errorlevel%
