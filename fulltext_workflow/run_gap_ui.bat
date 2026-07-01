@echo off
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\streamlit.exe" run gap_ui.py %*
