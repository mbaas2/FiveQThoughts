@echo off
cd /d "%~dp0"
python -c "import app; app.ensure_windows_native_app()"
if exist "FiveQThoughts.exe" (
    start "" "FiveQThoughts.exe"
) else (
    python app.py
)
