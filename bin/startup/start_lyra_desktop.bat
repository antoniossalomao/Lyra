@echo off
REM Lyra como app desktop (Electron, casca fina em volta do front-end v2
REM servido pelo cerebro_maestro em :8000/ui). Reusa o Electron ja baixado
REM pela Lyra IDE em vez de instalar uma copia nova.

set ELECTRON_EXE=C:\Lyra_Project\Lyra_Core\Lyra_IDE\node_modules\electron\dist\electron.exe
set APP_DIR=C:\Lyra_Project\Lyra_Core\Lyra_Desktop

REM ELECTRON_RUN_AS_NODE forca o Electron a rodar como Node puro (sem janela)
REM quando herdado de um processo pai que tambem roda sobre Electron.
set ELECTRON_RUN_AS_NODE=

"%ELECTRON_EXE%" "%APP_DIR%"
