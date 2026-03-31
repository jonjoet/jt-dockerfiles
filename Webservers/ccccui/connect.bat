@echo off
REM ============================================================
REM CHOPCHOP Web Interface - SSH Tunnel + Browser Launcher
REM
REM CONFIGURE THESE VALUES:
SET VM_USER=your_username        &REM <-- CHANGE THIS
SET VM_IP=your.vm.ip.address     &REM <-- CHANGE THIS
SET SSH_KEY=C:\Users\you\.ssh\id_rsa  &REM <-- CHANGE THIS
SET LOCAL_PORT=1721
REM ============================================================

echo Opening SSH tunnel to %VM_IP%:%LOCAL_PORT%...
start /b ssh -N -L %LOCAL_PORT%:localhost:%LOCAL_PORT% %VM_USER%@%VM_IP% -i "%SSH_KEY%"

REM Give the tunnel a moment to establish
timeout /t 3 /nobreak >nul

echo Opening browser...
start http://localhost:%LOCAL_PORT%

echo.
echo SSH tunnel is running. Close this window to disconnect.
echo If the page doesn't load, wait a few seconds and refresh.
pause
