# 自我蒸餾的共用啟動器：每個「N-xxx.cmd」都只是呼叫這個檔案。
#   run.ps1 collect [--limit 30 ...]   1 蒐集
#   run.ps1 sample  [--tries 4]        2 挑選
#   run.ps1 build                      3 建立資料集
#   run.ps1 setup                      4 安裝訓練環境
#   run.ps1 train   [--check]          5 訓練
#   run.ps1 export  [訓練名稱]          6 匯出到 Ollama（預設最新一次訓練）
#   run.ps1 compare [模型名稱]          7 比較新舊（預設最新匯出的模型）
# 不用 param()：像 --limit 30 這種參數要原封不動交給 Python，不能讓 PowerShell 當成自己的參數解析。
if ($args.Count -lt 1) { throw '用法：run.ps1 <步驟> [參數…]' }
$Step = [string]$args[0]
$Rest = @($args | Select-Object -Skip 1 | ForEach-Object { [string]$_ })

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'                                     # 進度即時顯示（也讓全自動的紀錄檔收到）
$env:HF_HOME = Join-Path $Root 'data\distill\hf-cache'          # 原始權重下載到 F 槽，不佔 C 槽
$App = Join-Path $Root '.venv\Scripts\python.exe'
$Train = Join-Path $Root 'distill-env\Scripts\python.exe'
$Work = if ($env:TEACHING_DISTILL_DIR) { $env:TEACHING_DISTILL_DIR } else { Join-Path $Root 'data\distill' }
$Runs = Join-Path $Work 'runs'

function Need-TrainEnv {
    if (-not (Test-Path $Train)) { throw '還沒有訓練環境，請先執行 4-安裝訓練環境.cmd' }
}

function Free-Gpu {
    # 讓 Ollama 先把模型移出顯示卡，訓練才有完整的 32 GB
    foreach ($name in @('qwen3.8:27b-q4_K_M')) {
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/generate' -Method Post -TimeoutSec 30 `
                -ContentType 'application/json' -Body (@{ model = $name; keep_alive = 0 } | ConvertTo-Json) | Out-Null
        } catch { }
    }
    try {
        $loaded = Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/ps' -TimeoutSec 10
        foreach ($m in $loaded.models) {
            Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/generate' -Method Post -TimeoutSec 30 `
                -ContentType 'application/json' -Body (@{ model = $m.name; keep_alive = 0 } | ConvertTo-Json) | Out-Null
        }
    } catch { }
}

function Start-ModelServer {
    & $App -c "from workflow_v2.engine import ensure_server; ensure_server()"
    if ($LASTEXITCODE) { throw '模型服務沒有啟動成功' }
}

function Latest-Run([string]$need) {
    if (-not (Test-Path $Runs)) { return $null }
    $found = Get-ChildItem $Runs -Directory | Where-Object { Test-Path (Join-Path $_.FullName $need) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return $found
}

switch ($Step) {
    'collect' { & $App -m distill.collect @Rest }
    'sample'  { & $App -m distill.sample @Rest }
    'build'   { & $App -m distill.build @Rest }
    'setup'   { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'setup_train.ps1') }
    'train'   {
        Need-TrainEnv
        Write-Host '先讓 Ollama 釋放顯示卡記憶體…'
        Free-Gpu
        & $Train -m distill.train @Rest
    }
    'export'  {
        Need-TrainEnv
        if ($Rest.Count -eq 0) {
            $run = Latest-Run 'adapter'
            if (-not $run) { throw '找不到已完成的訓練（data\distill\runs\*\adapter）' }
            $Rest = @($run.Name)
            Write-Host "匯出最新一次訓練：$($run.Name)"
        }
        Start-ModelServer
        Free-Gpu
        & $Train -m distill.export @Rest
    }
    'compare' {
        if ($Rest.Count -eq 0 -or $Rest[0].StartsWith('--')) {
            $run = Latest-Run 'ollama-name.txt'
            if (-not $run) { throw '找不到已匯出的模型，請先執行 6-匯出到Ollama.cmd' }
            $name = (Get-Content (Join-Path $run.FullName 'ollama-name.txt') -Encoding UTF8 -Raw).Trim()
            Write-Host "比較最新匯出的模型：$name"
            $Rest = @($name) + $Rest
        }
        & $App -m distill.evaluate @Rest
    }
    default { throw "不認得的步驟：$Step" }
}
exit $LASTEXITCODE
