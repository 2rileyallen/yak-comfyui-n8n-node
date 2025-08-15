@echo off
setlocal

set ENV_NAME=yak_comfyui_env
echo [INFO] Starting ComfyUI services...

echo [INFO] Launching ComfyUI server with Sage Attention enabled...
echo [INFO] Look for the message 'Using sage attention' on startup.
echo [INFO] Access the UI at http://127.0.0.1:8188

:: Use the correct --use-sage-attention flag
cmd /c "conda run -n %ENV_NAME% python ComfyUI\main.py --use-sage-attention"

endlocal
pause
:eof