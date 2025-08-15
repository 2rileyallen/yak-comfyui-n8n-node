@echo off
setlocal enabledelayedexpansion

:: ==========================================================================
:: Yak ComfyUI Node - Environment Setup Script (v4.1 - Gatekeeper Deps)
:: ==========================================================================
echo.
echo [INFO] Starting Yak ComfyUI Node setup process...
echo.

set ENV_NAME=yak_comfyui_env

:: --- Step 1: Prerequisite Checks ---
echo [STEP 1/7] Checking for prerequisites (Git, Python, and Conda)...
where git >nul 2>&1
if !errorlevel! neq 0 ( echo [ERROR] Git not found. & pause & goto :eof )
echo  - Git found.
where python >nul 2>&1
if !errorlevel! neq 0 ( echo [ERROR] Python not found. & pause & goto :eof )
echo  - Python found.
where conda >nul 2>&1
if !errorlevel! neq 0 ( echo [ERROR] Conda not found. Please install Miniconda. & pause & goto :eof )
echo  - Conda found.
echo [SUCCESS] Prerequisites check passed.
echo.

:: --- Step 2: Clone or Update OFFICIAL ComfyUI ---
echo [STEP 2/7] Setting up OFFICIAL ComfyUI repository...
if not exist "ComfyUI" (
    echo  - ComfyUI directory not found. Cloning repository...
    git clone https://github.com/comfyanonymous/ComfyUI.git
    if !errorlevel! neq 0 ( echo [ERROR] Failed to clone ComfyUI. & pause & goto :eof )
) else (
    echo  - ComfyUI directory found. Updating repository...
    cd ComfyUI & git pull & cd ..
)
echo [SUCCESS] ComfyUI repository is up to date.
echo.

:: --- Step 3: Create Conda Environment ---
echo [STEP 3/7] Configuring Conda environment '!ENV_NAME!'...
call conda env list | findstr /B /C:"!ENV_NAME! " >nul
if !errorlevel! equ 0 (
    echo  - Conda environment '!ENV_NAME!' already exists. Please remove it first for this major update.
    echo  - Run: conda env remove -n !ENV_NAME!
    pause
    goto :eof
) else (
    echo  - Creating Conda environment with Python 3.11...
    call conda create --name !ENV_NAME! python=3.11 -y
    echo  - Verifying environment creation...
    call conda env list | findstr /B /C:"!ENV_NAME! " >nul
    if !errorlevel! neq 0 ( echo [ERROR] Failed to create or verify Conda environment. & pause & goto :eof )
)
echo [SUCCESS] Conda environment is ready.
echo.

:: --- Step 4: Install Core Dependencies ---
echo [STEP 4/7] Installing core dependencies...
echo.
:: UPDATED: Installing PyTorch 2.5.1 to match latest SageAttention
echo  --- Installing PyTorch 2.5.1, this may take a while...
cmd /c "conda run -n !ENV_NAME! conda install pytorch=2.5.1 torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia -y"
if !errorlevel! neq 0 ( echo [ERROR] Failed to install PyTorch. & pause & goto :eof )
echo.
echo  --- Installing ComfyUI core requirements...
cmd /c "conda run -n !ENV_NAME! pip install -r ComfyUI\requirements.txt"
if !errorlevel! neq 0 ( echo [ERROR] Failed to install ComfyUI requirements. & pause & goto :eof )
echo [SUCCESS] Core dependencies installed.
echo.

:: --- Step 5: Install Sage Attention and Dependencies ---
echo [STEP 5/7] Installing Sage Attention and its dependencies...
:: UPDATED: Pointing to the latest SageAttention v2.2.0 wheel for PyTorch 2.5.1
set SAGE_WHL_NAME=sageattention-2.2.0+cu124torch2.5.1.post2-cp39-abi3-win_amd64.whl
set SAGE_WHL_URL=https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows.post2/%SAGE_WHL_NAME%

echo.
echo  --- Installing Triton...
cmd /c "conda run -n !ENV_NAME! pip install -U triton-windows"
if !errorlevel! neq 0 ( echo [ERROR] Failed to install Triton. & pause & goto :eof )

echo.
echo  --- Downloading Sage Attention binary via PowerShell (TLS 1.2)...
powershell -command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointType]::Tls12; Invoke-WebRequest -Uri '%SAGE_WHL_URL%' -OutFile '%SAGE_WHL_NAME%' -UseBasicParsing"
if !errorlevel! neq 0 ( echo [ERROR] Failed to download Sage Attention .whl file. & pause & goto :eof )

echo.
echo  --- Installing Sage Attention from downloaded file...
cmd /c "conda run -n !ENV_NAME! pip install %SAGE_WHL_NAME%"
if !errorlevel! neq 0 ( echo [ERROR] Failed to install Sage Attention. & pause & goto :eof )

echo.
echo  --- Cleaning up downloaded files...
del %SAGE_WHL_NAME%
echo [SUCCESS] Sage Attention installed.
echo.

:: --- Step 6: Install ComfyUI-Manager ---
echo [STEP 6/7] Installing the ComfyUI-Manager...
set MANAGER_PATH=ComfyUI\custom_nodes\ComfyUI-Manager
if not exist "%MANAGER_PATH%" (
    echo  - Cloning ComfyUI-Manager...
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git "%MANAGER_PATH%"
    if !errorlevel! neq 0 ( echo [ERROR] Failed to clone ComfyUI-Manager. & pause & goto :eof )
    echo  - Installing ComfyUI-Manager requirements...
    cmd /c "conda run -n !ENV_NAME! pip install -r ""%MANAGER_PATH%\requirements.txt"""
    if !errorlevel! neq 0 ( echo [ERROR] Failed to install ComfyUI-Manager requirements. & pause & goto :eof )
) else (
    echo  - ComfyUI-Manager already exists. Skipping installation.
)
echo [SUCCESS] ComfyUI-Manager installed.
echo.

:: --- Step 7: Install Gatekeeper Dependencies ---
echo [STEP 7/7] Installing Gatekeeper service dependencies...
cmd /c "conda run -n !ENV_NAME! pip install fastapi ""uvicorn[standard]"" sqlalchemy httpx websockets"
if !errorlevel! neq 0 ( echo [ERROR] Failed to install Gatekeeper dependencies. & pause & goto :eof )
echo [SUCCESS] Gatekeeper dependencies installed.
echo.

echo ==========================================================================
echo  SETUP COMPLETE!
echo  Run 'start_services.bat' to launch ComfyUI with Sage Attention.
echo ==========================================================================
echo.

endlocal
pause
:eof
