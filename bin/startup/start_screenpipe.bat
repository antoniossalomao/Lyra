@echo off
REM Screenpipe — gravação contínua de tela + áudio, dados em D:\Lyra_Vault\Screenpipe
REM Instalar: npm install -g @screenpipe/cli
REM MCP server exposto em http://127.0.0.1:3030 (conectar no Claude settings.json)

powershell -NoProfile -Command "$c=New-Object System.Net.Sockets.TcpClient; try{$ok=$c.ConnectAsync('127.0.0.1',3030).Wait(300)}catch{$ok=$false}; $c.Close(); if($ok){exit 1}else{exit 0}"
if %ERRORLEVEL% NEQ 0 (
    echo Screenpipe ja esta rodando na porta 3030.
    exit /b 0
)

where screenpipe >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] screenpipe nao encontrado. Instale com: npm install -g @screenpipe/cli
    exit /b 1
)

screenpipe ^
  --data-dir "D:\Lyra_Vault\Screenpipe" ^
  --fps 0.5 ^
  --port 3030 ^
  >> "C:\Lyra_Project\bin\startup\screenpipe_startup.log" 2>&1
