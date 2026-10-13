# 4 安裝訓練環境：在 F:\教材ai\distill-env 建一個獨立的 Python 3.12 環境（不動教材AI本身的 .venv）。
# 內容：PyTorch（依顯示卡驅動選 CUDA 版本）＋ Unsloth（QLoRA 訓練、合併、轉 GGUF）。
# 需要網路，約下載 5～8 GB，第一次約 15～40 分鐘。可以重複執行，已裝好的會跳過。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Env = Join-Path $Root 'distill-env'
$Py = Join-Path $Env 'Scripts\python.exe'

# 1. Python 3.12：優先用教材AI內建的那一份
$Base = Join-Path $Root 'runtime\python-official\python.exe'
if (-not (Test-Path $Base)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $Base = (& py -3.12 -c "import sys; print(sys.executable)").Trim() }
}
if (-not $Base -or -not (Test-Path $Base)) { throw '找不到 Python 3.12（runtime\python-official\python.exe 或 py -3.12）' }
$version = (& $Base -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
Write-Host "使用 Python $version：$Base"
if ($version -notin @('3.10', '3.11', '3.12', '3.13')) { throw "Unsloth 需要 Python 3.10～3.13，目前是 $version" }

# 2. 顯示卡與 CUDA 版本（RTX 50 系列至少要 CUDA 12.8 的 PyTorch）
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $smi) { throw '找不到 nvidia-smi，請先安裝或更新 NVIDIA 顯示卡驅動' }
$info = (& nvidia-smi) -join "`n"
$cuda = [regex]::Match($info, 'CUDA Version:\s*([0-9]+)\.([0-9]+)')
if (-not $cuda.Success) { throw '讀不到驅動支援的 CUDA 版本' }
$major = [int]$cuda.Groups[1].Value; $minor = [int]$cuda.Groups[2].Value
Write-Host "驅動支援 CUDA $major.$minor"
if ($major -ge 13) { $wheel = 'cu130' }
elseif ($major -eq 12 -and $minor -ge 8) { $wheel = 'cu128' }
else { throw "驅動只支援 CUDA $major.$minor；RTX 5090 需要 12.8 以上，請先更新 NVIDIA 驅動" }

# 3. 虛擬環境
if (-not (Test-Path $Py)) {
    Write-Host "建立 $Env …"
    & $Base -m venv $Env
    if ($LASTEXITCODE) { throw '建立虛擬環境失敗' }
}
& $Py -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE) { throw 'pip 更新失敗' }

# 4. PyTorch（CUDA 版）
$ErrorActionPreference = 'Continue'      # Windows PowerShell 5.1 會把被導向的 stderr 當成錯誤
$hasTorch = (& $Py -c "import torch; print(int(torch.cuda.is_available()))" 2>$null)
$ErrorActionPreference = 'Stop'
if ($hasTorch -ne '1') {
    Write-Host "安裝 PyTorch（$wheel）…"
    & $Py -m pip install torch torchvision torchaudio --index-url "https://download.pytorch.org/whl/$wheel"
    if ($LASTEXITCODE) { throw 'PyTorch 安裝失敗' }
}

# 5. Unsloth（會一併安裝 transformers、peft、trl、bitsandbytes、datasets）
Write-Host '安裝 Unsloth …'
& $Py -m pip install --upgrade unsloth
if ($LASTEXITCODE) { throw 'Unsloth 安裝失敗' }

# 6. 檢查
Write-Host '檢查環境 …'
& $Py -c @"
import torch
assert torch.cuda.is_available(), 'PyTorch 看不到顯示卡'
name = torch.cuda.get_device_name(0)
total = torch.cuda.get_device_properties(0).total_memory / 2**30
print(f'顯示卡：{name}，{total:.0f} GB；PyTorch {torch.__version__}，CUDA {torch.version.cuda}')
import unsloth, transformers, peft
print(f'Unsloth {unsloth.__version__}、transformers {transformers.__version__}、peft {peft.__version__}')
"@
if ($LASTEXITCODE) { throw '環境檢查沒有通過，請把上面的訊息貼給 Claude' }
Write-Host ''
Write-Host '訓練環境完成。下一步：5-訓練.cmd（建議先跑一次「5-訓練.cmd --check」確認格式）'
