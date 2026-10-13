param([switch]$InstallOCR,[switch]$InstallEngine,[switch]$InstallPPT,[switch]$InstallImages,[switch]$NoLaunch)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot)
Set-Location -LiteralPath $root
if(!(Test-Path -LiteralPath (Join-Path $root 'config.yaml'))){
    Copy-Item -LiteralPath (Join-Path $root 'config.example.yaml') -Destination (Join-Path $root 'config.yaml')
}
$env:PYTHONUTF8='1'
$env:UV_PYTHON_INSTALL_DIR=Join-Path $root 'runtime\python'
$env:UV_CACHE_DIR=Join-Path $root 'runtime\uv-cache'
New-Item -ItemType Directory -Force -Path (Join-Path $root 'runtime'),(Join-Path $root 'logs') | Out-Null
function Check-Exit {if($LASTEXITCODE -ne 0){throw 'Installation failed. See the message above; retry after checking your network and disk space.'}}
function Test-EnvironmentPython([string]$Python) {
    if(!(Test-Path -LiteralPath $Python -PathType Leaf)){return $false}
    try {
        & $Python -I -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.prefix != sys.base_prefix else 1)' *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        if($_.Exception -is [System.Management.Automation.ApplicationFailedException]){
            if($_.Exception.InnerException.NativeErrorCode -in @(4551,577,1260) -and (Get-AuthenticodeSignature -LiteralPath $Python).Status -eq 'NotSigned'){
                Write-Host 'Windows rejected unsigned Python. Preparing the official signed distribution.'
                return $false
            }
            throw "Cannot start Python at $Python. Check the Windows application control policy or executable permissions. Original error: $($_.Exception.Message)"
        }
        return $false
    }
}
function Get-OfficialPython {
    $target=Join-Path $root 'runtime\python-official'
    $exe=Join-Path $target 'python.exe'
    if(!(Test-Path -LiteralPath $exe)){
        $installer=Join-Path $root 'runtime\python-3.12.10-amd64.exe'
        if(!(Test-Path -LiteralPath $installer)){
            Write-Host 'Downloading official Python 3.12 installer...'
            Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
        }
        $signature=Get-AuthenticodeSignature -LiteralPath $installer
        if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation(?:,|$)'){
            throw 'Official Python installer signature verification failed.'
        }
        Write-Host 'Installing official Python without changing PATH or installing the launcher...'
        $arguments='/quiet InstallAllUsers=0 TargetDir="'+$target+'" PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=0 AssociateFiles=0 Shortcuts=0 /log "'+(Join-Path $root 'logs\python-install.log')+'"'
        $process=Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
        if($process.ExitCode -ne 0){throw "Official Python install failed ($($process.ExitCode)). See logs\python-install.log."}
    }
    $signature=Get-AuthenticodeSignature -LiteralPath $exe
    if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation(?:,|$)'){throw 'Official Python executable signature verification failed.'}
    & $exe -I -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' | Out-Host
    Check-Exit
    return $exe
}
function Ensure-Environment([string]$Name,[string]$Uv) {
    if($Name -notin @('.venv','.venv-marker','.venv-images')){throw 'Unknown environment name.'}
    $folder=[IO.Path]::GetFullPath((Join-Path $root $Name))
    $python=Join-Path $folder 'Scripts\python.exe'
    if(Test-EnvironmentPython $python){return $python}
    $basePython=Get-OfficialPython
    if(Test-Path -LiteralPath $folder){
        # Keep the old environment for recovery; never delete it during repair.
        $backup=$folder+'.broken-'+[Guid]::NewGuid().ToString('N')
        if((Split-Path $folder -Parent) -ne $root -or (Split-Path $backup -Parent) -ne $root){throw 'Unsafe environment repair path.'}
        Write-Host "Preserving unusable environment as $backup"
        Move-Item -LiteralPath $folder -Destination $backup
    }
    Write-Host "Creating $Name with official Python 3.12..."
    & $basePython -m venv $folder | Out-Host
    Check-Exit
    if(!(Test-EnvironmentPython $python)){throw "Environment creation did not produce a working Python: $python"}
    return $python
}
function Get-Uv {
    $uv=Join-Path $root 'runtime\uv.exe'
    if(Test-Path -LiteralPath $uv){return $uv}
    if($env:PROCESSOR_ARCHITECTURE -ne 'AMD64'){throw 'This installer supports Windows x64. Other platforms require a matching installer.'}
    Write-Host 'Downloading Python environment installer...'
    $zip=Join-Path $root 'runtime\uv-download.zip'
    Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $entry=$archive.Entries | Where-Object {$_.Name -eq 'uv.exe'} | Select-Object -First 1
        if(!$entry){throw 'Invalid environment installer archive.'}
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$uv,$true)
    } finally {$archive.Dispose()}
    Remove-Item -LiteralPath $zip
    return $uv
}
if($InstallPPT){
    $nodeCommand=Get-Command node -ErrorAction SilentlyContinue
    $node=Join-Path $root 'runtime\node\node.exe'
    if($nodeCommand){$node=$nodeCommand.Source}
    if(!(Test-Path -LiteralPath $node)){
        Write-Host 'Downloading Node.js LTS...'
        $release=Invoke-RestMethod 'https://nodejs.org/dist/index.json' | Where-Object {$_.lts -and $_.files -contains 'win-x64-zip'} | Select-Object -First 1
        $filename='node-'+$release.version+'-win-x64.zip'
        $zip=Join-Path $root ('runtime\'+$filename)
        Invoke-WebRequest -UseBasicParsing ('https://nodejs.org/dist/'+$release.version+'/'+$filename) -OutFile $zip
        $sums=(Invoke-WebRequest -UseBasicParsing ('https://nodejs.org/dist/'+$release.version+'/SHASUMS256.txt')).Content
        $expected=($sums -split "`n" | Where-Object {$_.Trim().EndsWith(' '+$filename)}).Trim().Split(' ')[0]
        if((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower() -ne $expected){throw 'Node.js checksum mismatch'}
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $root 'runtime') -Force
        Rename-Item -LiteralPath (Join-Path $root ('runtime\node-'+$release.version+'-win-x64')) -NewName 'node'
        Remove-Item -LiteralPath $zip
    }
    $npm=Join-Path (Split-Path $node) 'node_modules\npm\bin\npm-cli.js'
    $folder=Join-Path $root 'runtime\pptx';New-Item -ItemType Directory -Force -Path $folder | Out-Null
    & $node $npm install --prefix $folder --no-audit --no-fund --ignore-scripts 'pptxgenjs@4.0.1';Check-Exit
    exit 0
}
if($InstallImages){
    $uv=Get-Uv
    $python=Ensure-Environment '.venv-images' $uv
    & $uv pip install --python $python 'torch==2.7.1' --index-url 'https://download.pytorch.org/whl/cu128';Check-Exit
    & $uv pip install --python $python 'diffusers>=0.35,<1' 'transformers>=4.44,<5' accelerate safetensors sentencepiece protobuf huggingface_hub;Check-Exit
    exit 0
}
if($InstallEngine){
    $existing=Get-Command ollama -ErrorAction SilentlyContinue
    $installed=Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if($existing -or (Test-Path -LiteralPath $installed)){exit 0}
    $folder=Join-Path $root 'runtime\ollama'
    if(Test-Path -LiteralPath (Join-Path $folder 'ollama.exe')){exit 0}
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Write-Host 'Downloading local model engine (may require several GB)...'
    $zip=Join-Path $root 'runtime\ollama-download.zip'
    Invoke-WebRequest -UseBasicParsing 'https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip' -OutFile $zip
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach($entry in $archive.Entries){
            $target=[IO.Path]::GetFullPath((Join-Path $folder $entry.FullName))
            if(!$target.StartsWith($folder+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe archive path.'}
        }
    } finally {$archive.Dispose()}
    Expand-Archive -LiteralPath $zip -DestinationPath $folder -Force
    Remove-Item -LiteralPath $zip
    exit 0
}
if($InstallOCR){
    $uv=Get-Uv
    $python=Ensure-Environment '.venv-marker' $uv
    $index='https://download.pytorch.org/whl/cpu'
    if(Get-Command nvidia-smi -ErrorAction SilentlyContinue){$index='https://download.pytorch.org/whl/cu128'}
    & $uv pip install --python $python 'torch==2.7.1' 'torchvision==0.22.1' --index-url $index;Check-Exit
    & $uv pip install --python $python 'marker-pdf==1.10.1';Check-Exit
    exit 0
}
$python=Join-Path $root '.venv\Scripts\python.exe'
$ready=$false
if(Test-EnvironmentPython $python){
    try {
        & $python -c 'import streamlit,requests,yaml,pymupdf,pptx,docx,filelock,psutil,jsonschema,playwright,PIL' 2>$null
        $ready=$LASTEXITCODE -eq 0
    } catch {$ready=$false}
}
if(!$ready){
    $uv=Get-Uv
    $python=Ensure-Environment '.venv' $uv
    Write-Host 'Installing application dependencies...'
    & $python -m pip install --disable-pip-version-check --timeout 30 --retries 2 -r (Join-Path $root 'requirements.txt');Check-Exit
}
if (!(Test-Path -LiteralPath (Join-Path $root 'runtime\ollama\ollama.exe')) -and
    !(Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe')) -and
    !(Get-Command ollama -ErrorAction SilentlyContinue)) {
    & $PSCommandPath -InstallEngine
    if ($LASTEXITCODE -ne 0) { throw 'Local model engine installation failed.' }
}
if(!$NoLaunch){& $python (Join-Path $root 'launch_v2.py');Check-Exit}
