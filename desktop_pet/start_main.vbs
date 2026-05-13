Option Explicit

Dim shell
Dim fso
Dim baseDir
Dim dataDir
Dim logPath
Dim showErrorBat
Dim runtimeFile
Dim pythonExe
Dim exitCode

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
dataDir = fso.BuildPath(baseDir, "data")
logPath = fso.BuildPath(dataDir, "start_main_error.log")
showErrorBat = fso.BuildPath(dataDir, "show_start_main_error.bat")
runtimeFile = fso.BuildPath(dataDir, "runtime_python.txt")
pythonExe = ""

If Not fso.FolderExists(dataDir) Then
    fso.CreateFolder dataDir
End If

shell.CurrentDirectory = baseDir
WriteText logPath, "Desktop Pet startup check" & vbCrLf & "Time: " & Now & vbCrLf & vbCrLf

If fso.FileExists(runtimeFile) Then
    pythonExe = NormalizePath(ReadText(runtimeFile))
End If

If pythonExe = "" Then
    ShowError "Runtime Python was not configured. Please run setup_env.bat first."
    WScript.Quit 1
End If

If Not fso.FileExists(pythonExe) Then
    ShowError "Runtime Python was not found: " & pythonExe & ". Please run setup_env.bat again."
    WScript.Quit 1
End If

exitCode = RunHidden("cmd.exe /c " & Q(Q(pythonExe) & " -c " & Q("import PySide6, requests") & " >> " & Q(logPath) & " 2>&1"))
If exitCode <> 0 Then
    ShowError "Project dependencies are missing or incomplete. Please run setup_env.bat first."
    WScript.Quit exitCode
End If

AppendText logPath, "Starting main.py..." & vbCrLf
exitCode = RunHidden("cmd.exe /c " & Q(Q(pythonExe) & " main.py >> " & Q(logPath) & " 2>&1"))
If exitCode <> 0 Then
    ShowError "main.py exited with code " & CStr(exitCode) & "."
    WScript.Quit exitCode
End If

WScript.Quit 0

Function Q(value)
    Q = """" & value & """"
End Function

Function RunHidden(command)
    RunHidden = shell.Run(command, 0, True)
End Function

Sub WriteText(path, text)
    Dim file
    Set file = fso.OpenTextFile(path, 2, True)
    file.Write text
    file.Close
End Sub

Function ReadText(path)
    Dim file
    Set file = fso.OpenTextFile(path, 1, False)
    ReadText = file.ReadAll
    file.Close
End Function

Function NormalizePath(value)
    value = Replace(value, vbCr, "")
    value = Replace(value, vbLf, "")
    value = Replace(value, vbTab, "")
    value = Trim(value)
    If Len(value) > 0 Then
        If Left(value, 1) = ChrW(&HFEFF) Then
            value = Mid(value, 2)
        End If
    End If
    NormalizePath = value
End Function

Sub AppendText(path, text)
    Dim file
    Set file = fso.OpenTextFile(path, 8, True)
    file.Write text
    file.Close
End Sub

Sub ShowError(message)
    AppendText logPath, vbCrLf & message & vbCrLf
    WriteText showErrorBat, "@echo off" & vbCrLf & _
        "title Desktop Pet Startup Error" & vbCrLf & _
        "echo Desktop Pet failed to start." & vbCrLf & _
        "echo." & vbCrLf & _
        "type " & Q(logPath) & vbCrLf & _
        "echo." & vbCrLf & _
        "pause" & vbCrLf
    shell.Run Q(showErrorBat), 1, False
End Sub
