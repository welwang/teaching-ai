# 教材簡報工作室

Windows 本機教材製作工具。讀取教材、規劃教學大綱、編寫與審核內容，輸出可編輯的 PowerPoint、PDF 預覽、教師備課稿與學習單。

控制台提供任務進度、製作時間、顯卡負載、暫停續作與修改記錄。教學提示詞可按任務調整，不改動系統預設。

## 啟動

需要 Windows x64、本機模型與可用的 Python 3.12 環境。

1. 將 `config.example.yaml` 複製為 `config.yaml`，依主機環境調整服務位址與模型。
2. 執行 `bootstrap.ps1` 安裝環境；加 `-NoLaunch` 可只安裝。
3. 執行 `Start-TeachingAI.cmd` 開啟控制台。

首次安裝與模型設定見 [系統說明](第二代系統說明.md)及 [模型配置](DENSE-27B-配置說明.md)。

## 程式結構

| 路徑 | 用途 |
| --- | --- |
| `app_v2.py`、`workflow_v2/panel.py` | 網頁入口與操作介面 |
| `workflow_v2/panel_style.py`、`panel_view.py` | 配色、排版與監控元件 |
| `workflow_v2/pipeline.py`、`worker.py` | 教材生成與工作佇列 |
| `workflow_v2/qa.py`、`visual_qa.py` | 內容與版面檢查 |
| `workflow_v2/change_log.py` | 簡報修改記錄 |
| `distill/` | 本機模型蒸餾工具 |
| `tests/` | 功能與回歸測試 |

模型、教材、生成成果與本機設定放在 `models/`、`data/` 和 `config.yaml`，不納入 Git 版本。

## 驗證與打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.\build_installer.ps1
```

設計規則見 [排版說明](docs/排版設計說明.md)，修改記錄格式見 [紀錄說明](docs/簡報修改記錄.md)。
