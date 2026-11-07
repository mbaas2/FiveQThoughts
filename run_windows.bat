@echo off
cd /d "%~dp0"
rem Builds the native Windows host (native\windows, needs the .NET SDK) on first start / after changes.
python -c "import app; app.ensure_windows_native_app()"
if exist "native\windows\bin\Release\FiveQThoughts.exe" (
    rem The host starts app.py as backend itself (tray icon, Ctrl+Alt+Q, WebView2 window)
    start "" "native\windows\bin\Release\FiveQThoughts.exe"
) else (
    python app.py
)
