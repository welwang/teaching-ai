# 全自動：1 蒐集 → 2 挑選 → 3 建立資料集 → 4 安裝訓練環境（需要時）→ 5 訓練 → 6 匯出 → 7 比較 → 採用或不採用 → 關閉教材AI。
#   auto.ps1                     預設蒐集 100 個單元，完成後關閉教材AI
#   auto.ps1 --units 60          蒐集 60 個單元
#   auto.ps1 --poweroff          全部完成後關機（關機前有 120 秒可用 shutdown /a 取消）
# 可以中途關掉視窗；再執行一次會從停下的地方繼續（已蒐集、已評分的不會重做）。
# 全程紀錄：data\distill\auto-日期.log；最後結果：data\distill\reports\auto-result.txt
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Units = 100; $PowerOff = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    switch ([string]$args[$i]) {
        '--units'    { $i++; $Units = [int]$args[$i] }
        '--poweroff' { $PowerOff = $true }
        default      { throw "不認得的參數：$($args[$i])" }
    }
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Run = Join-Path $PSScriptRoot 'run.ps1'
$App = Join-Path $Root '.venv\Scripts\python.exe'
$Work = Join-Path $Root 'data\distill'
$Reports = Join-Path $Work 'reports'
New-Item -ItemType Directory -Force -Path $Reports | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmm'
Start-Transcript -Path (Join-Path $Work "auto-$Stamp.log") -Append | Out-Null
$Result = Join-Path $Reports 'auto-result.txt'
$env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'

function Say([string]$text) { Write-Host ''; Write-Host ("[{0}] {1}" -f (Get-Date -Format 'MM-dd HH:mm'), $text) -ForegroundColor Cyan }

function Step([string]$name, [string[]]$stepArgs) {
    Say $name
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Run @stepArgs | ForEach-Object { Write-Host $_ }   # 經過 PowerShell，紀錄檔才收得到
    if ($LASTEXITCODE) { throw "$name 沒有完成（代碼 $LASTEXITCODE）" }
}

function Stop-Services {
    # 停掉教材AI的製作程序、模型服務與生圖服務（資料保留，佇列暫停）
    & $App (Join-Path $Root 'shutdown.py')
    if ($LASTEXITCODE) { Write-Host '有服務沒有停下來，訓練可能因顯示卡記憶體不足而失敗' -ForegroundColor Yellow }
}

function Close-System {
    Say '關閉教材AI …'
    try { & $App (Join-Path $Root 'shutdown.py') --include-ui } catch { Write-Host $_ }
    if ($PowerOff) {
        Say '120 秒後關機（要取消請在命令列輸入 shutdown /a）'
        & shutdown.exe /s /t 120 /c "教材AI 自我蒸餾已完成，電腦將關機"
    }
}

$outcome = ''
try {
    Say "開始全自動流程：蒐集 $Units 個單元 → 挑選 → 資料集 → 訓練 → 匯出 → 比較"

    # 1. 蒐集：分批跑，已完成的單元會自動略過
    $progressFile = Join-Path $Work 'collect-progress.json'
    while ($true) {
        $finished = 0
        if (Test-Path $progressFile) {
            $p = Get-Content $progressFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $finished = @($p.PSObject.Properties | Where-Object { $_.Value.finished }).Count
        }
        $left = $Units - $finished
        if ($left -le 0) { break }
        $before = $finished
        Step "1 蒐集（已完成 $finished / $Units 個單元）" @('collect', '--limit', [string][Math]::Min(20, $left))
        $p = Get-Content $progressFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue | ConvertFrom-Json
        $after = if ($p) { @($p.PSObject.Properties | Where-Object { $_.Value.finished }).Count } else { 0 }
        if ($after -le $before) { Say '教材庫沒有更多可用的單元，或這一批全部失敗，蒐集到此為止。'; break }
    }

    # 2、3
    Step '2 挑選（評分＋重寫）' @('sample')
    Step '3 建立資料集' @('build')
    $stats = Get-Content (Join-Path $Work 'dataset\stats.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($stats.train -lt 200) {
        throw "可訓練的資料只有 $($stats.train) 筆（少於 200），先不訓練。請增加 --units 再執行一次。"
    }

    # 4. 訓練環境
    $trainPy = Join-Path $Root 'distill-env\Scripts\python.exe'
    $ready = $false
    if (Test-Path $trainPy) {
        $ErrorActionPreference = 'Continue'
        & $trainPy -c "import torch, unsloth; assert torch.cuda.is_available()" 2>$null
        $ready = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = 'Stop'
    }
    if (-not $ready) { Step '4 安裝訓練環境' @('setup') }

    # 5. 訓練前讓出整張顯示卡
    $free = (Get-PSDrive -Name (Split-Path -Qualifier $Root).TrimEnd(':')).Free / 1GB
    if ($free -lt 150) { throw ("磁碟只剩 {0:N0} GB，訓練＋匯出需要約 150 GB 以上，先停止。" -f $free) }
    Say '停止教材AI的製作與模型服務，讓出顯示卡 …'
    Stop-Services
    # 上次中斷、已訓練完但還沒比較的那一次，直接接著用
    $pending = Get-ChildItem (Join-Path $Work 'runs') -Directory -Filter 'auto-*' -ErrorAction SilentlyContinue |
        Where-Object { (Test-Path (Join-Path $_.FullName 'adapter')) -and -not (Test-Path (Join-Path $_.FullName 'compared.txt')) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $runName = if ($pending) { $pending.Name } else { "auto-$Stamp" }
    $runDir = Join-Path $Work "runs\$runName"
    if (-not (Test-Path (Join-Path $runDir 'adapter'))) {
        Step '5 訓練（數小時）' @('train', '--name', $runName)
    }

    # 6、7
    if (-not (Test-Path (Join-Path $runDir 'ollama-name.txt'))) { Step '6 匯出到 Ollama' @('export', $runName) }
    $model = (Get-Content (Join-Path $runDir 'ollama-name.txt') -Raw -Encoding UTF8).Trim()
    Step '7 比較新舊模型' @('compare', $model)
    Set-Content -Path (Join-Path $runDir 'compared.txt') -Value (Get-Date -Format 'yyyy-MM-dd HH:mm') -Encoding UTF8

    # 8. 依比較結果決定
    $report = Get-ChildItem $Reports -Filter 'compare-*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $verdict = (Get-Content $report.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).verdict
    if ($verdict -eq 'adopt') {
        & $App -m distill.adopt $model
        if ($LASTEXITCODE) { throw '寫入 config.yaml 失敗' }
        $outcome = "完成並已採用新模型 $model（config.yaml 的 distilled_model）。要還原：把那一行改回 # distilled_model: 開頭。"
    } else {
        $outcome = "完成，但新模型 $model 沒有比較好，維持原本的模型。詳見 $($report.FullName -replace '\.json$', '.md')"
    }
    Say $outcome
} catch {
    $outcome = '中途停止：' + $_.Exception.Message
    Say $outcome
} finally {
    Set-Content -Path $Result -Value ("{0}`r`n{1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $outcome) -Encoding UTF8
    Close-System
    Stop-Transcript | Out-Null
}
