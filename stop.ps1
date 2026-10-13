param([switch]$ShowMessage)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $python) {
    & $python (Join-Path $PSScriptRoot 'shutdown.py') --include-ui
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stop all application processes.' }
}
if ($ShowMessage) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        'Teaching AI has stopped. Data is retained and jobs remain paused.',
        'Teaching AI'
    )
}
