Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
$gcm = Get-Process git-credential-manager -ErrorAction SilentlyContinue | Select-Object -First 1
if ($gcm) {
  [Win32]::ShowWindow($gcm.MainWindowHandle, 9) | Out-Null
  [Win32]::SetForegroundWindow($gcm.MainWindowHandle) | Out-Null
  Write-Output ("Fenetre GCM au premier plan (PID " + $gcm.Id + ")")
} else {
  Write-Output "Pas de GCM en cours"
}
