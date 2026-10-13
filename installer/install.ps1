param([string]$PackageRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference='Stop'
function Get-InstallTarget([string]$Text) {
    if([string]::IsNullOrWhiteSpace($Text)){throw '請選擇安裝位置'}
    $target=[IO.Path]::GetFullPath($Text).TrimEnd('\')
    $source=[IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
    if($target -eq [IO.Path]::GetPathRoot($target).TrimEnd('\')){throw '請選擇專用安裝資料夾，不能使用磁碟根目錄'}
    if($target -eq $source -or ($target+'\').StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase) -or ($source+'\').StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase)){throw '安裝資料夾不能與解壓縮的安裝包重疊'}
    if((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw '不能安裝至連結資料夾'}
    return $target
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form=New-Object Windows.Forms.Form
$form.Text='教材 AI 安裝程式';$form.Size=New-Object Drawing.Size(620,300);$form.StartPosition='CenterScreen'
$iconFile=Join-Path $PackageRoot 'assets\brand\favicon.ico';if(Test-Path -LiteralPath $iconFile){$form.Icon=New-Object Drawing.Icon($iconFile)}
$logoFile=Join-Path $PackageRoot 'assets\brand\logo-64.png';if(Test-Path -LiteralPath $logoFile){$pic=New-Object Windows.Forms.PictureBox;$pic.Image=[Drawing.Image]::FromStream([IO.MemoryStream]::new([IO.File]::ReadAllBytes($logoFile)));$pic.SizeMode='Zoom';$pic.Size=New-Object Drawing.Size(56,56);$pic.Location=New-Object Drawing.Point(530,14);$form.Controls.Add($pic)}
$title=New-Object Windows.Forms.Label;$title.Text='教材 AI 系統';$title.Font=New-Object Drawing.Font('Microsoft JhengHei',18,[Drawing.FontStyle]::Bold);$title.AutoSize=$true;$title.Location=New-Object Drawing.Point(24,20);$form.Controls.Add($title)
$info=New-Object Windows.Forms.Label;$info.Text='此安裝包不含 AI 模型、教材資料庫或既有教材。';$info.AutoSize=$true;$info.Location=New-Object Drawing.Point(26,62);$form.Controls.Add($info)
$label=New-Object Windows.Forms.Label;$label.Text='安裝位置：';$label.AutoSize=$true;$label.Location=New-Object Drawing.Point(26,112);$form.Controls.Add($label)
$box=New-Object Windows.Forms.TextBox;$box.Text=Join-Path $env:LOCALAPPDATA 'TeachingAI';$box.Size=New-Object Drawing.Size(420,25);$box.Location=New-Object Drawing.Point(105,108);$form.Controls.Add($box)
$browse=New-Object Windows.Forms.Button;$browse.Text='瀏覽…';$browse.Location=New-Object Drawing.Point(535,106);$browse.Add_Click({$dialog=New-Object Windows.Forms.FolderBrowserDialog;if($dialog.ShowDialog() -eq 'OK'){$box.Text=$dialog.SelectedPath}});$form.Controls.Add($browse)
$status=New-Object Windows.Forms.Label;$status.Text='準備安裝';$status.AutoSize=$true;$status.Location=New-Object Drawing.Point(26,160);$form.Controls.Add($status)
$install=New-Object Windows.Forms.Button;$install.Text='開始安裝';$install.Size=New-Object Drawing.Size(120,36);$install.Location=New-Object Drawing.Point(450,205)
$install.Add_Click({try{$target=Get-InstallTarget $box.Text;$status.Text='正在複製系統檔案…';$install.Enabled=$false;New-Item -ItemType Directory -Force -Path $target | Out-Null;Get-ChildItem -LiteralPath $PackageRoot -Force | Where-Object {$_.Name -notin @('install.ps1','package-manifest.json')} | Copy-Item -Destination $target -Recurse -Force;New-Item -ItemType Directory -Force -Path (Join-Path $target 'data/workflow-v2'),(Join-Path $target 'data/uploads'),(Join-Path $target 'logs') | Out-Null;$status.Text='安裝完成';[Windows.Forms.MessageBox]::Show('安裝完成。請使用 Start-TeachingAI.cmd 啟動。','Teaching AI');$form.Close()}catch{$install.Enabled=$true;$status.Text='安裝失敗：'+$_.Exception.Message}});$form.Controls.Add($install)
$form.Add_Shown({$form.Activate()});[void]$form.ShowDialog()
