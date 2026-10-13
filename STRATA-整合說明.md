# Strata 本地推論整合（未啟用）

目前改用 Qwen Dense 27B Q4_K_M；Strata 安裝已取消，未完成下载已清理。下列為保留的備選部署文件，詳見 `DENSE-27B-配置說明.md`。

參考：[文章](https://ai-coding.wiselychen.com/strata-qwen38-flash-next-rtx5090-1m-context/)、[官方專案](https://github.com/Niko1221/Strata/tree/v0.1.30)。

- 固定 Strata v0.1.30（commit `30ec18ec7094550fcc594fd948220d511d80464e`）。
- Qwen3.8-Flash-Next IQ3_S：模型 snapshot `ed59f92082b1e93c0e96d60a8b11aab089b52f09`，中文 MTP 詞表。
- Windows 原生、獨立 Python 環境、無 Docker／WSL；API 僅監聽 `127.0.0.1:8088`。
- 備選整合可讓規劃、編寫、審核與學習單共用此本地模型；目前不使用此配置。
- 目前主機為 64GB RAM。官方 v0.1.30 安裝器將 IQ3_S 的 256K 要求降為 128K，故使用 **131072 上下文、int8 KV、resident experts**，不啟用 YaRN 和實驗性 speed projection。
- 不啟用 1M 上下文；固定 128K，不啟用 YaRN 上下文延伸。

## 安裝與使用

執行 `Install-Strata.cmd`。下載約 84GB 權重、約 5GB MTP；resident 模式另需約 50GB experts 檔案。首次下載需要網路，完成後推論不連網。中斷後重新執行可續傳。

安裝紀錄：`logs/strata-install.log`。來源和版本記錄：`runtime/strata/teaching-ai-source.json`、`teaching-ai-installed.json`；完成後鎖存 Python 套件清單。

安裝完成後，重新整理「製作教材」模型選單，選擇 **Qwen3.8 Flash Next · Strata IQ3_S**。規劃、編寫、審核都用同一模型；一次製作一份教材。既有 Ollama 工作仍保留原選擇。

工作開始時載入模型；控制介面保留運作並显示載入狀態。載入文字模型前卸載 Ollama 已載入的權重，切回 Ollama 時停止本系統的 Strata。`Shut down` 會停止本系統的 Strata 和子程序，保留控制介面。

## 輸出與監控

Strata 不改動教材、版型或簡報輸出資料夾。來源仍由原管線分段整理，輸出仍經 JSON 結構驗證、內容審核和安全排版。

v0.1.30 沒有 `response_format` 強制 Schema 功能；Schema 以指令傳入，程式驗證並有限修復，不能保證零重試。回覆中斷或達輸出長度限制時，不採用不完整內容。

本機傳輸內部使用 SSE 以支援中止；介面不逐字顯示。完成後將 usage 和 timings 轉成既有監控格式，統計輸入、輸出、快取 token 與生成耗時。取消工作時關閉連線，官方服務會停止當前生成。

服務紀錄：`logs/strata.out.log`、`logs/strata.err.log`，引擎紀錄位於 `runtime/strata/strata-iq3_s.log`。服務檢查包含獨立 Strata 健康狀態。

安裝包包含整合程式與下載入口；不包含 `runtime`、`models`、教材、資料庫及運行紀錄。
