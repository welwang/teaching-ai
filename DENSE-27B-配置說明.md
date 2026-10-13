# 本機模型配置

適用版本：v1.0.0。模型政策由 `workflow_v2/model_policy.py` 與 `config.yaml` 管理。

## 1. 預設配置

```yaml
ollama_url: http://127.0.0.1:11435
preferred_model: qwen3.8:27b-q4_K_M
generation_architecture: dense_27b
model_selection: fixed
generation_context: 32768
ollama_parallel: 1
write_concurrency: 1
```

`preferred_model` 是本機 Ollama 的實際名稱。發布包不附模型，部署需確認列表含該名稱，或改為已安裝且已驗證的名稱。專案不根據標籤推定權重的架構、來源或授權。

解析、規劃、編寫、審核和修復使用管理員設定。`model_selection: fixed` 讓後端按此政策綁定請求，一般使用者不在製作頁選模型。

## 2. 服務與模型目錄

專案啟動的 Ollama 使用 `127.0.0.1:11435`，模型目錄為 `models/ollama/`。其他服務可能使用不同連接埠或權重目錄，需先確認再匯入。

模型端點僅允許 loopback HTTP，不接受帶帳密、路徑、查詢或 fragment 的 URL。

```powershell
Invoke-RestMethod http://127.0.0.1:11435/api/tags
.\.venv\Scripts\python.exe -m workflow_v2.health
```

## 3. 上下文

設定允許 8192、16384、32768 詞元，預設 32768。固定上下文便於配置資源並追蹤輸入是否超出限制。

長教材先分段整理；逐頁請求只帶當頁引用與教學規則。來源過長或模型出錯時，不無條件丟棄引用內容來掩蓋問題。

## 4. 並行度

預設一次製作一份教材、單頁編寫。配置兩個服務槽位與並行編寫前，確認顯存、模型服務和實測吞吐量。

`concurrency.py` 依條件限制並行；記憶體不足時記錄回退，改用單槽。總結頁依賴前頁內容，不與未完成前頁任意並行。

```powershell
.\.venv\Scripts\python.exe -m workflow_v2.timing data\workflow-v2\jobs\工作編號
```

比較總耗時、重寫次數和輸出量再調整。模型、生圖與其他 GPU 程式可能同時占用顯存，不能只看權重檔案大小。

## 5. 蒸餾模型

比較後可設定文字模型：

```yaml
distilled_model: 已驗證的蒸餾模型名稱
```

留空或移除欄位即回到 `preferred_model`。影像請求仍回到基礎模型，文字微調不代表影像能力也經驗證。

流程、隔離資料和採用條件見 [distill/README.md](distill/README.md)。一般使用不必建立訓練環境。

## 6. 圖像與資源

掃描辨識或含影像請求需要基礎模型具備對應能力。插圖生成是獨立本機服務，安裝包預設關閉。

生圖前協調文字模型占用，失敗保留缺圖診斷並嘗試受控替代。模型配置與生成速度應以部署主機的實際教材驗證。
