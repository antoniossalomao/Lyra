@echo off
powershell -NoProfile -Command "$c=New-Object System.Net.Sockets.TcpClient; try{$ok=$c.ConnectAsync('127.0.0.1',8090).Wait(300)}catch{$ok=$false}; $c.Close(); if($ok){exit 1}else{exit 0}"
if %ERRORLEVEL% NEQ 0 exit /b 0
cd /d C:\Lyra_Project\Lyra_Core\Memoria_Lyra
powershell -NoProfile -Command "if ((Get-Item 'C:\Lyra_Project\bin\startup\surreal_startup.log' -ErrorAction SilentlyContinue).Length -gt 5MB) { Move-Item 'C:\Lyra_Project\bin\startup\surreal_startup.log' 'C:\Lyra_Project\bin\startup\surreal_startup.log.old' -Force }"
surreal start --log warn --username root --password root --bind 127.0.0.1:8090 "surrealkv://db_cortex" >> C:\Lyra_Project\bin\startup\surreal_startup.log 2>&1
