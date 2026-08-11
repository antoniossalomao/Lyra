@echo off
REM embed_service.py — microservico de embedding BGE-M3 (:8001).
REM O cerebro_maestro DEPENDE deste servico desde a migracao BGE-M3 (26/06/2026).
REM idle-unload 600s: libera a VRAM quando a Lyra fica ociosa.
REM 30/06/2026: venv_embed (5GB) aposentado - o Python global foi atualizado pra
REM torch 2.6+cu124 (exigido pelo bge-m3, so pesos .bin sem safetensors), entao
REM roda direto nele agora. Processo continua isolado do cerebro_maestro.py
REM (fault isolation + idle-unload preservados, so mudou o interprete).
powershell -NoProfile -Command "$c=New-Object System.Net.Sockets.TcpClient; try{$ok=$c.ConnectAsync('127.0.0.1',8001).Wait(300)}catch{$ok=$false}; $c.Close(); if($ok){exit 1}else{exit 0}"
if %ERRORLEVEL% NEQ 0 exit /b 0
cd /d C:\Lyra_Project\Lyra_Ollama
powershell -NoProfile -Command "if ((Get-Item 'C:\Lyra_Project\bin\startup\embed_startup.log' -ErrorAction SilentlyContinue).Length -gt 5MB) { Move-Item 'C:\Lyra_Project\bin\startup\embed_startup.log' 'C:\Lyra_Project\bin\startup\embed_startup.log.old' -Force }"
"C:\Users\anton\AppData\Local\Programs\Python\Python312\python.exe" embed_service.py --idle 600 >> C:\Lyra_Project\bin\startup\embed_startup.log 2>&1
