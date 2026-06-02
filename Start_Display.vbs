' ============================================================
'  WT Nuke Counter - 獨立顯示視窗 (選用,不需要 OBS)
' ------------------------------------------------------------
'  開一個乾淨小視窗顯示計數器。資料來自後端 backend.py 的
'  127.0.0.1:8112 — 後端有送 CORS 標頭,所以「不需要」關閉
'  瀏覽器 web security,用一般 Chrome / Edge 即可。
'
'  前提:backend.py 要先在跑 (執行 Start_Tracker.vbs,或設成開機自啟)。
'
'  用法:
'    1) 先確定 Start_Tracker.vbs 已啟動 (後端在數)。
'    2) 雙擊本檔 → 跳出小視窗顯示即時計數。
'  視窗大小可改下面 --window-size。
' ============================================================
Option Explicit

Dim fso, shell, scriptDir, indexUrl, profileDir, browserPath, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
indexUrl = "file:///" & Replace(scriptDir & "\startdisplay.html", "\", "/")

' 獨立 profile,避免跟你平常的 Chrome 視窗互卡 (但不需要關 web security)
profileDir = scriptDir & "\_display_profile"

browserPath = FindBrowser(fso, shell)
If browserPath = "" Then
    MsgBox "找不到 Chrome 或 Edge。請先安裝 Chrome,或把瀏覽器路徑加進本腳本的 candidates 清單。", _
           48, "WT Nuke Counter"
    WScript.Quit 1
End If

cmd = """" & browserPath & """" & _
      " --app=""" & indexUrl & """" & _
      " --user-data-dir=""" & profileDir & """" & _
      " --window-size=420,420" & _
      " --no-first-run --no-default-browser-check"

shell.Run cmd, 1, False

' ------------------------------------------------------------
Function FindBrowser(fso, shell)
    Dim candidates, p, i, localApp
    localApp = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    candidates = Array( _
        "C:\Program Files\Google\Chrome\Application\chrome.exe", _
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", _
        localApp & "\Google\Chrome\Application\chrome.exe", _
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", _
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe" )
    For i = 0 To UBound(candidates)
        p = candidates(i)
        If fso.FileExists(p) Then
            FindBrowser = p
            Exit Function
        End If
    Next
    FindBrowser = ""
End Function
