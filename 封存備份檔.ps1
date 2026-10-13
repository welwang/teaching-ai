# 把程式資料夾裡累積的 .bak-* 備份檔與 tmp 暫存檔「移動」到 F:\教材ai-備份\程式封存-<日期>\，不刪除任何檔案。
# 保留路徑結構，需要時可直接複製回來。最近 2 天內修改過的備份檔留在原處（剛做的修改還可就近還原）。
# 用法：在 F:\教材ai 按右鍵「用 PowerShell 執行」，或執行 封存備份檔.cmd。加 -WhatIf 只列出不移動。
param([int]$KeepDays = 2, [switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dest = Join-Path (Split-Path -Parent $root) ("教材ai-備份\程式封存-" + $stamp)
$cutoff = (Get-Date).AddDays(-$KeepDays)

$targets = @()
foreach ($dir in @($root, (Join-Path $root 'workflow_v2'), (Join-Path $root 'tests'))) {
    if (Test-Path $dir) {
        $targets += Get-ChildItem -LiteralPath $dir -File -Filter '*.bak-*' | Where-Object { $_.LastWriteTime -lt $cutoff }
    }
}
$tmp = Join-Path $root 'tmp'
if (Test-Path $tmp) { $targets += Get-ChildItem -LiteralPath $tmp -File -Recurse }

if (-not $targets) { Write-Host '沒有需要封存的檔案。'; exit 0 }
$bytes = ($targets | Measure-Object Length -Sum).Sum
Write-Host ("找到 {0} 個檔案，共 {1:N1} MB，將移到：{2}" -f $targets.Count, ($bytes / 1MB), $dest)
if ($WhatIf) { $targets | ForEach-Object { $_.FullName.Substring($root.Length + 1) }; exit 0 }

foreach ($file in $targets) {
    $relative = $file.FullName.Substring($root.Length + 1)
    $target = Join-Path $dest $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Move-Item -LiteralPath $file.FullName -Destination $target
}
if (Test-Path $tmp) {
    Get-ChildItem -LiteralPath $tmp -Directory -Recurse | Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force) } | Remove-Item
}
Write-Host ("完成：已移動 {0} 個檔案到 {1}" -f $targets.Count, $dest)
