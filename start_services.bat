@echo off
setlocal

set ENV_NAME=yak_comfyui_env
echo [INFO] Starting all ComfyUI services...
echo [INFO] Two new command prompt windows will open.

:: The 'START "Window Title"' command opens a new command prompt window.
:: We use 'cmd /c' to ensure the conda command runs correctly and '& pause' keeps the window open if it closes or errors.

:: Start the ComfyUI Server in a new window
echo [INFO] Launching ComfyUI Server...
START "ComfyUI Server" cmd /c "conda run -n %ENV_NAME% python ComfyUI\main.py --use-sage-attention & pause"

:: Give ComfyUI a moment to start up before launching the Gatekeeper
timeout /t 5 >nul

:: Start the Gatekeeper Service in a new window
echo [INFO] Launching Gatekeeper Service...
START "Gatekeeper Service" cmd /c "conda run -n %ENV_NAME% python gatekeeper.py & pause"

echo [INFO] Both services have been launched in separate windows.
echo [INFO] You can close this window now.

endlocal