Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\Lyra_Project\bin\startup\start_qdrant.bat", 0, False
WshShell.Run "C:\Lyra_Project\bin\startup\start_surreal.bat", 0, False
WshShell.Run "C:\Lyra_Project\bin\startup\start_embed.bat", 0, False
WshShell.Run "C:\Lyra_Project\bin\startup\start_cerebro.bat", 0, False
