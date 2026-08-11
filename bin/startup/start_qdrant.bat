@echo off
powershell -NoProfile -Command "$c=New-Object System.Net.Sockets.TcpClient; try{$ok=$c.ConnectAsync('127.0.0.1',6333).Wait(300)}catch{$ok=$false}; $c.Close(); if($ok){exit 1}else{exit 0}"
if %ERRORLEVEL% NEQ 0 exit /b 0
set QDRANT__STORAGE__STORAGE_PATH=C:\Lyra_Project\qdrant_data
set QDRANT__SERVICE__HTTP_PORT=6333
set QDRANT__SERVICE__HOST=127.0.0.1
cd /d C:\Lyra_Project\bin
powershell -NoProfile -Command "if ((Get-Item 'C:\Lyra_Project\bin\startup\qdrant_startup.log' -ErrorAction SilentlyContinue).Length -gt 5MB) { Move-Item 'C:\Lyra_Project\bin\startup\qdrant_startup.log' 'C:\Lyra_Project\bin\startup\qdrant_startup.log.old' -Force }"
"C:\Lyra_Project\bin\qdrant.exe" >> C:\Lyra_Project\bin\startup\qdrant_startup.log 2>&1
