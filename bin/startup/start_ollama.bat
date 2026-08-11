@echo off
powershell -NoProfile -Command "if ((Get-Item 'C:\Lyra_Project\bin\startup\ollama_startup.log' -ErrorAction SilentlyContinue).Length -gt 5MB) { Move-Item 'C:\Lyra_Project\bin\startup\ollama_startup.log' 'C:\Lyra_Project\bin\startup\ollama_startup.log.old' -Force }"
ollama serve >> C:\Lyra_Project\bin\startup\ollama_startup.log 2>&1
