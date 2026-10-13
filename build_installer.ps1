param([string]$Output = '', [string]$Version = '1.0.0')
$ErrorActionPreference='Stop'
if($Version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$'){throw '版本格式應為 major.minor.patch'}
$root=[IO.Path]::GetFullPath($PSScriptRoot)
if(!$Output){$Output=Join-Path $root 'dist\TeachingAI-Installer.zip'}
$Output=[IO.Path]::GetFullPath($Output)
$dist=Split-Path -Parent $Output;$stage=[IO.Path]::GetFullPath((Join-Path $root 'dist\TeachingAI-package'))
if(!(($stage+'\').StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase))){throw '打包暫存資料夾必須位於目前系統資料夾內'}
if(Test-Path -LiteralPath $stage){
    if((Get-Item -LiteralPath $stage -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw '不能覆寫連結資料夾'}
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$include=@('app_v2.py','launch_v2.py','shutdown.py','bootstrap.ps1','requirements.txt','README.md','第二代系統說明.md','操作說明-任務控制台.md','DENSE-27B-配置說明.md','STRATA-整合說明.md','open_ui.ps1','close_ui.ps1','config.example.yaml','workflow_v2','assets\workflow-v2','assets\brand','docs','distill','installer\install.ps1','installer\Install-TeachingAI.cmd','installer\INSTALL.txt','Start-TeachingAI.cmd','開啟教材AI.cmd','關閉教材AI.cmd','stop.ps1','install_strata.py','Install-Strata.cmd')
foreach($item in $include){
    $src=Join-Path $root $item
    if(!(Test-Path -LiteralPath $src)){throw "缺少打包檔案：$item"}
    $files=if(Test-Path -LiteralPath $src -PathType Container){Get-ChildItem -LiteralPath $src -File -Recurse}else{Get-Item -LiteralPath $src}
    foreach($file in $files){
        if($file.Name -match '\.bak|\.pyc$|\.pyo$|\.tmp$|\.partial' -or $file.FullName -match '[\\/]__pycache__[\\/]'){continue}
        if($file.Attributes -band [IO.FileAttributes]::ReparsePoint){throw '不能打包連結檔案'}
        $relative=$file.FullName.Substring($root.Length+1);$dest=Join-Path $stage $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
    }
}
$config=Join-Path $stage 'config.yaml'
Copy-Item -LiteralPath (Join-Path $stage 'config.example.yaml') -Destination $config
$portable=Get-Content -LiteralPath $config -Encoding UTF8 | Where-Object {$_ -notmatch '^(strata_url|strata_config|image_generation_python|image_generation_launcher):'} | ForEach-Object {$_ -replace '^image_generation_enabled:\s*true','image_generation_enabled: false'}
$portable | Set-Content -LiteralPath $config -Encoding UTF8
$manifest=[ordered]@{format=1;version=$Version;created=(Get-Date).ToUniversalTime().ToString('o');contains=@('application source','logo','installer','documentation','distillation tools');excluded=@('AI models','material database','source materials','.venv','data','logs','runtime','models','generated outputs','tests');requirements='requirements.txt'}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stage 'package-manifest.json') -Encoding UTF8
New-Item -ItemType Directory -Force -Path $dist | Out-Null
if(Test-Path -LiteralPath $Output){Remove-Item -LiteralPath $Output -Force}
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $Output -CompressionLevel Optimal
$hash=(Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash
Set-Content -LiteralPath ($Output+'.sha256') -Value "$hash  $([IO.Path]::GetFileName($Output))" -Encoding ASCII
Write-Host "已建立：$Output";Write-Host "SHA256：$hash"
