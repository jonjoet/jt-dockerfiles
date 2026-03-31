@echo off
REM ============================================================
REM CHOPCHOP Web Interface - SSH Tunnel + Browser Launcher
REM
REM CONFIGURE THESE VALUES:
SET VM_USER=your_username             &REM <-- CHANGE THIS
SET VM_IP=your.vm.ip.address          &REM <-- CHANGE THIS
SET SSH_KEY=C:\Users\you\.ssh\id_rsa  &REM <-- CHANGE THIS
SET LOCAL_PORT=1721
REM ============================================================

REM Re-launch inside Windows Terminal if we're not already in it
if "%WT_SESSION%"=="" (
    where wt >nul 2>nul
    if not errorlevel 1 (
        wt.exe -- "%~f0"
        exit /b
    )
)

echo Opening browser in 3 seconds...
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%LOCAL_PORT%"

echo Connecting SSH tunnel to %VM_IP%:%LOCAL_PORT%...
echo Close this window to disconnect.
echo.
ssh -N -L %LOCAL_PORT%:localhost:%LOCAL_PORT% %VM_USER%@%VM_IP% -i "%SSH_KEY%"
