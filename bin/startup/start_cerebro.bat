@echo off
setlocal enabledelayedexpansion

powershell -NoProfile -Command "$c=New-Object System.Net.Sockets.TcpClient; try{$ok=$c.ConnectAsync('127.0.0.1',8000).Wait(300)}catch{$ok=$false}; $c.Close(); if($ok){exit 1}else{exit 0}"
if %ERRORLEVEL% NEQ 0 exit /b 0

REM Espera Qdrant(6333) + SurrealDB(8090) + Ollama(11434) + embed_service(8001).
REM embed_service e dependencia obrigatoria desde a migracao BGE-M3 (sem fallback MiniLM).
REM TcpClient bruto em vez de Test-NetConnection: ~270ms vs ~7s por chamada medido
REM neste ambiente (26x mais lento) - com 4 portas x 60 tentativas isso inflava o
REM timeout de boot de "2 minutos" nominal pra ate ~28min reais num boot lento.
set TENTATIVAS=0
:esperar
set /a TENTATIVAS+=1
if !TENTATIVAS! GTR 60 goto seguir
powershell -NoProfile -Command "function T($p){$c=New-Object System.Net.Sockets.TcpClient; try{$r=$c.ConnectAsync('127.0.0.1',$p).Wait(300)}catch{$r=$false}; $c.Close(); return $r}; if ((T 6333) -and (T 8090) -and (T 11434) -and (T 8001)) { exit 0 } else { exit 1 }"
if %ERRORLEVEL% EQU 0 goto seguir
timeout /t 2 /nobreak >nul
goto esperar

:seguir
cd /d C:\Lyra_Project\Lyra_Ollama
powershell -NoProfile -Command "if ((Get-Item 'C:\Lyra_Project\bin\startup\cerebro_startup.log' -ErrorAction SilentlyContinue).Length -gt 5MB) { Move-Item 'C:\Lyra_Project\bin\startup\cerebro_startup.log' 'C:\Lyra_Project\bin\startup\cerebro_startup.log.old' -Force }"
"C:\Users\anton\AppData\Local\Programs\Python\Python312\python.exe" cerebro_maestro.py >> C:\Lyra_Project\bin\startup\cerebro_startup.log 2>&1
