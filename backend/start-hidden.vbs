' Starts codex-callid-fix with no console window.
'
' Used by the HKCU Run autostart entry (manage.js autostart on) and as a
' double-click launcher. "boot" reconciles the last on/off state: it starts the
' proxy and re-applies config.toml when the tool was ON, or restores things
' when it was OFF.
Option Explicit

Dim fso, sh, dir, nodeExe, nodeFile, f, cmd, candidate
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
nodeExe = "node"
nodeFile = dir & "\node-path.txt"

' manage.js autostart on stores the exact node.exe path here so logon does not
' depend on PATH.
If fso.FileExists(nodeFile) Then
  Set f = fso.OpenTextFile(nodeFile, 1)
  If Not f.AtEndOfStream Then
    candidate = Trim(f.ReadLine())
    If Len(candidate) > 0 And fso.FileExists(candidate) Then nodeExe = candidate
  End If
  f.Close
End If

cmd = """" & nodeExe & """ """ & dir & "\manage.js"" boot"
sh.Run cmd, 0, False
