' 後端計數器啟動器 (隱藏視窗)。backend.py 會持續輪詢 8111、維護 state.json、
' 並在 127.0.0.1:8112 提供 /state 給 overlay 讀。開機自啟:把本檔捷徑放進 shell:startup。
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
' 設定工作目錄,確保 backend.py 讀寫的是「本資料夾內」的 state.json / config.json
' (否則相對路徑會落到 System32,你的累積數字會讀不到)
WshShell.CurrentDirectory = currentDir
WshShell.Run "pythonw.exe """ & currentDir & "\backend.py""", 0, False
