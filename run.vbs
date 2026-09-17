Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root

ffbin = root & "\runtime\ffmpeg\bin"
If fso.FolderExists(ffbin) Then
    sh.Environment("Process")("PATH") = ffbin & ";" & sh.Environment("Process")("PATH")
End If

pyw = root & "\runtime\python\tools\pythonw.exe"
py = root & "\runtime\python\tools\python.exe"
If fso.FileExists(pyw) Then
    sh.Run """" & pyw & """ launch.py", 0, False
ElseIf fso.FileExists(py) Then
    sh.Run """" & py & """ launch.py", 0, False
Else
    MsgBox "Не найден runtime\python\tools\pythonw.exe." & vbCrLf & _
           "Скопируйте папку программы целиком, вместе с runtime\.", _
           48, "Video Hover Preview"
End If
