$ErrorActionPreference='Stop'
try { & (Join-Path $PSScriptRoot 'stop.ps1') -ShowMessage }
catch {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        ('Shutdown did not complete: ' + $_.Exception.Message),
        'Teaching AI'
    )
    exit 1
}
