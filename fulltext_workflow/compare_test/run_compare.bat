@echo off
cd /d "%~dp0.."
set PY=..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m compare_test.compare %*
