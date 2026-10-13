param([int]$WaitForDownloadPid=0)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$installer=Join-Path $root 'runtime\OllamaSetup.exe'
$status=Join-Path $root 'logs\ollama-install-status.json'
function Set-Status([string]$Stage,[string]$Detail) {
    @{stage=$Stage;detail=$Detail;updated=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
}
function Test-Installer {
    if(!(Test-Path -LiteralPath $installer)){return $false}
    $sig=Get-AuthenticodeSignature -LiteralPath $installer
    return $sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -match '(^|, )O=Ollama Inc\.(,|$)'
}
try {
    Set-Status 'downloading' 'Downloading the official Ollama Windows installer; installation follows signature verification.'
    if($WaitForDownloadPid){
        $downloadProcess=Get-Process -Id $WaitForDownloadPid -ErrorAction SilentlyContinue
        if($downloadProcess){$downloadProcess.WaitForExit()}
    }
    if(!(Test-Installer)){
        & curl.exe --location --fail --retry 5 --retry-delay 10 --connect-timeout 30 --continue-at - --output $installer 'https://github.com/ollama/ollama/releases/download/v0.34.2/OllamaSetup.exe'
        if($LASTEXITCODE -ne 0){throw 'Download incomplete. Run install_ollama.ps1 again to resume.'}
    }
    if(!(Test-Installer)){throw 'Ollama Inc. installer signature verification failed.'}
    Set-Status 'installing' 'Signature verified. Installing Ollama for the current user.'
    $arguments='/VERYSILENT /NORESTART /SUPPRESSMSGBOXES /LOG="'+(Join-Path $root 'logs\ollama-setup.log')+'"'
    $process=Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if($process.ExitCode -ne 0){throw "Ollama installer failed: $($process.ExitCode). See logs\ollama-setup.log."}
    $exe=Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if(!(Test-Path -LiteralPath $exe)){throw 'Installed Ollama executable was not found at the default location.'}
    $version=(& $exe --version 2>&1 | Out-String).Trim()
    if($LASTEXITCODE -ne 0){throw "Ollama version check failed: $version"}
    Set-Status 'complete' $version
} catch {
    Set-Status 'failed' $_.Exception.Message
    throw
}
