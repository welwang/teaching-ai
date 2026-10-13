# 變更記錄 2026-10-04

修改前備份：`F:\教材ai-備份\修改前-20261004-100210\`（程式碼，不含 .venv、模型、data、runtime、dist、logs）。每個被修改的檔案旁另有 `.bak-20261004-…` 備份。

## 新增
- `workflow_v2/age_bands.py`：四個年段規則。
- `workflow_v2/deck_check.py`：成品離線檢查。
- `workflow_v2/console_state.py`、`console_view.py`、`console_theme.py`：控制台資料層、畫面元件、主題（4 種）。
- `tests/test_deck_check.py`（15）、`tests/test_console.py`（23）、`tests/test_worker_timeout.py`（5）。
- `操作說明-任務控制台.md`、本檔。

## 修改
- `pipeline.py`：逐頁提示詞改用年段字數與互動規則；渲染後呼叫成品檢查，寫入 `deck-validation.json` 與 `result.json`。
- `pedagogy.py`：系統提示加入年段語氣規則（**提示詞指紋改變，續跑中的舊工作可能重寫已完成頁面**）。
- `images.py`、`renderer.py`：統一圖片出處行。
- `contracts.py`：`result` 增加選填 `deck_validation`。
- `store.py`：支援環境變數 `TEACHING_AI_DATA`。
- `worker.py`：階段逾時隨頁數調整；逾時訊息中文化。
- `monitor_report.py`：新增三組中文錯誤說明。
- `monitor_ui.py`：監控面板改為每 2 秒更新、顯示新版面板。
- `ui.py`：整份重寫（精簡、無重複按鈕與說明、全中文、主題選擇、狀態變化即時刷新、中文下載標籤）。
- `app_v2.py`：頁面標題、側欄預設收合。
- `tests/test_monitoring_report.py`：英文殘留檢查改為只檢查可見文字（排除 HTML 標籤）。

## 驗證
- 全部測試 290 個通過（改版前基準 247 個）。
- 暫時預覽（非 8502 連接埠，已關閉）以無頭 Edge 驗證四種主題、1280／390 像素寬、減少動態效果、無例外、無英文介面文字。
- 未驗證：實際用模型生成一份簡報、PowerPoint 播放、安裝包重建、生圖服務（離線）。

## 需重新啟動
所有 Python 變更需「關閉教材AI.cmd」後「開啟教材AI.cmd」才生效。

# 後續更新（同日）

## 新增（後續）
- `workflow_v2/beautify.py`、`visual_qa.py`：自動美化與版面檢查。
- `workflow_v2/speedup.py`（跨工作快取、受控並行）、`workflow_v2/timing.py`（耗時分析，可 `python -m workflow_v2.timing <工作資料夾>`）。
- `tests/test_beautify.py`（18）、`tests/test_speedup.py`（12）、`tests/test_page_recovery.py` 等。

## 修改（後續）
- 移除模板：`template_styles.py` 改寫、停用選模板步驟；封存於 `F:\教材ai-備份\已移除模板-20261004\`。
- `qa.py`／`pipeline.py`／`local_images.py`／`monitor_report.py`：品檢誤判、保底頁與【待教師確認】、審核意見傳回、本機生圖預設關閉（`config.yaml`）。
- `console_state.py`／`console_view.py`／`console_theme.py`／`monitor_ui.py`／`ui.py`：控制台簡化（一句話＋一條進度條＋三個數字＋詳細資訊）、三個分頁、動畫、任務控制室風格版面（細狀態列、即時時鐘、單一大數字、細分隔線）。
- `pipeline.py`：美化／版面檢查階段、精簡輸出欄位、摘要與解析快取；`images.py`：搜尋並行與記憶；`worker.py`：預覽階段逾時 420 秒。

## 驗證（後續）
- 全部測試 343 個通過。暫時預覽（8591，已關閉）檢查 1280／390 像素、四種主題、減少動態效果，無橫向捲動、無例外。
- 速度數字：編寫、審核、發布等為實測；減少重寫、輸出欄位精簡、快取與並行的節省為依實測參數推算的估計，尚未用真實模型整體重跑量測。

## 需重新啟動（後續）
所有 Python 與 `config.yaml` 變更都需「關閉教材AI.cmd」後「開啟教材AI.cmd」。重啟前正在跑的工作仍使用舊程式。

# 第三批更新（同日晚間）

## 原創表達原則：教材只當參考，不照抄（本批最後加入）
- 新增 `workflow_v2/originality.py`：用字元 n-gram 比對投影片（學生看得到的欄位＋教師備註）與所引用的主教材頁，算出「最長連續相同字數」與「相同比例」。中文連續 30 字以上、或相同比例 ≥50% 且 ≥24 字視為照抄（英文為 70 字／≥60 字）；20 字以上為「接近」（只提醒）。「」『』“”內 40 字以內的短引用允許（每頁合計 80 字）。數字、標點、空白不計。
- 提示詞：逐頁提示詞加入「原創表達原則」（先理解、再用自己的話；換情境／人物／數字；禁止逐字複製；只可短引用並標示出處頁碼；例題要改寫成原創題）；大綱提示詞要求 topic／student_task 用自己的話；主教材摘要改成「整理成要點，不逐字抄錄」（摘要快取版本升為 v3）；學習單提示詞同樣加入原則。
- 自動檢查與改寫：`qa.check_slide(..., sources=…)` 新增 `verbatim_copy`（嚴重，屬硬性失敗）。寫頁、復原、審核三處都會比對；未通過就帶著「請用自己的話改寫」的具體指示請模型重寫（沿用既有重寫迴圈，審核階段最多兩輪）。學習單題目也會比對，照抄就重做。
- 成品檢查：`deck_check.check_deck(..., reference=…)` 新增 `verbatim_copy`（嚴重）與 `close_paraphrase`（提醒），寫入 `deck-validation.json`。
- 保底頁不再傾倒教材：`pipeline.fallback_page` 改為「待補提示頁」——標題用大綱主題、一行學生任務、一行「請老師對照主教材第 N 頁，用自己的話補上」；教師備註只留頁碼與失敗原因，不再放主教材原文；`quality-warnings.json` 的 mode 改為 `teacher_scaffold_no_source`。文字損壞時維持「無法可靠辨識」提示。介面與監控的中文說明同步改為「待補提示頁（不含教材原文）」。
- 唯讀稽核：`python -m workflow_v2.originality <工作編號前綴或資料夾>` 列出每頁相同比例。
- 測試：新增 `tests/test_originality.py`（17）；更新 `test_workflow_v2.py` 三個保底頁測試、`test_curriculum_prompts.py` 一個斷言。
- 既有簡報實測（10 份、237 頁，改前→改後）：照抄頁 87 → 5；整體相同比例 29.8% → 2.8%。87 頁中 82 頁是舊「原文保底頁」，新版保底頁為 0 重疊；其餘 5 頁是模型把課本題目幾乎照抄（比例題、除法規則、英語對話），新版會在審核階段退回重寫。（用保底頁換算，未實際重新呼叫模型。）
- 限制：只比對「所引用頁」的文字；掃描檔 OCR 錯字會降低偵測力；同義改寫（意思相同但字不同）不在偵測範圍，由提示詞負責。已完成的舊簡報不會自動改寫；若要處理，重新產生該頁（單頁修改）會套用新規則。
- 提示詞指紋未改，續跑中的工作不會因此重寫已完成頁面；新規則只對新寫的頁面與審核階段生效。

## 國中（7–9 年級）SpaceX 風格「mission」
- `template_styles.MISSION`（rev 2）：白底、近黑 `0F141A`、單一藍色強調 `0A5EA8`、細線 `D9DEE4`；封面與章節頁為近黑滿版。只套用 7–9 年級，1–6 年級樣式與修改前逐位元相同（已逐科驗證）。調整幾何時要提高 `MISSION['rev']`（快取以樣式雜湊命名）。
- `template_design.py`、`template_builder.py`、`renderer.py`、`beautify.py`：近黑封面／章節、強調短線與細線、細框雙欄卡片、淡色總結面板；頁碼改為右下純文字「n / 總頁數」；不使用圖示或裝飾圖形。年段規則與 `deck_check` 不變。
- 已生成的舊國中簡報可重新套用：`python -m workflow_v2.restyle [工作編號]`，或在「我的教材」按「套用新版面（不重寫內容）」。流程：備份 → 重新渲染（不呼叫模型）→ 失敗時還原。限制：最後優化（`final-optimized-deck.json`）的文字修改不會重新套用；圖片沿用已存紀錄，只有沒有有效圖片的頁面可能再取圖；僅以模擬工作資料夾測試。
- `tests/test_mission_style.py`（18）：對比、字級、只影響 7–9 年級、年段規則不變、重新套用行為、LibreOffice `visual_qa`（7／8／9 年級皆無殘留問題）。

## 控制台
- 每 1 秒更新（`config.yaml` 的 `console_refresh_seconds`，範圍 1–60，預設 1；需重新啟動才生效）。只更新即時面板，單次約 15 ms。瀏覽器分頁在背景時會自行降低計時頻率，系統沒有另外做伺服器端暫停。
- 7 種底色（白、米、淡藍、淡綠、柔霧灰、任務控制深色、午夜藍）× 5 種強調色（預設、橘、綠、紫、玫瑰），收在「外觀」選單；選擇會記住（`ui-prefs.json`）。所有文字與強調色對各底色對比 ≥4.5。
- Logo：`assets/brand/`（原圖、512／192／64／48 圓角 PNG、favicon.ico）；頂列顯示一個 logo、瀏覽器分頁圖示、安裝程式視窗圖示。簡報封面左下角 logo 預設關閉（`slide_logo: cover` 開啟）。
- `tests/test_brand_theme.py`。

## 生圖服務（Forge）
- `launch_v2.py` 啟動時背景拉起本機生圖服務（`workflow_v2/local_images.start_in_background`，不阻塞、不拋例外）；生圖時若服務沒開會自動重啟並等待，仍失敗才改用 Openverse／Wikimedia／圖解。系統頁以中文顯示狀態與原因。
- `config.yaml`：`image_generation_enabled: true`。安裝包內會強制改為 false。
- `tests/test_forge_start.py`。

## 速度與最後優化
- 最後優化只處理有問題的欄位（`polish_scope.py`、`final_optimizer.py`），無事可做時直接略過並標示「略過」。
- 並行：`OLLAMA_NUM_PARALLEL=2`、`write_concurrency=2`；記憶體不足或顯存不足自動降為 1（`concurrency.py`）。設定：`ollama_parallel`、`write_concurrency`、`parallel_min_total_vram_mb: 28000`、`parallel_min_free_vram_mb: 20000`。`tests/test_concurrency.py`。

## 錯誤檢視與修正（20 份真實工作、2982 個事件）
| 錯誤 | 原因 | 處理 | 測試 |
|---|---|---|---|
| `exposed_answer` ×35 | 題目最後的空白「答：」被當成洩漏答案 | 只有「答」後面有實際內容才算 | `AnswerLineTest` |
| `untraceable` ×77 | 小數點移位、10 的次方、長除法補 0 被誤判成數字無來源 | `derivable` 接受 10^k 倍數與 0、1 | `TraceableNumbersTest` |
| `stage_failed` ×9（來源頁） | 掃描頁辨識器的無害備註或空白頁讓整個工作中止 | 完整頁附備註照收，空白頁記錄後略過，不完整仍報錯 | `SourcePageTest` |
| `deck_validation_failed` ×6 與 aaaa/bbbb 事件 | 測試把假編號寫進真實稽核紀錄 | `log_event` 在真實資料根目錄丟棄像測試編號的 id | `TestIdsNeverReachTheRealLogTest` |
| `image_generation_unavailable` ×27 | 生圖服務沒啟動 | 見上「生圖服務」 | `test_forge_start.py` |
| `model_response_rejected` ×191（9/29） | 結構要求 `visual_model` | 先前已移除，之後沒有再發生 | — |
| 環境：pandas DLL 被 Windows 應用程式控制擋下 | 系統原則 | 程式無法處理，僅記錄 | — |

## 安裝包
- `build_installer.ps1`：加入 `assets\brand`、打包版強制 `image_generation_enabled: false`、移除本機路徑；安裝程式視窗圖示與 logo。

## 需重新啟動
「關閉教材AI.cmd」後「開啟教材AI.cmd」。更新頻率、外觀選單、Logo、生圖自動啟動、並行、國中新版面、錯誤修正與原創表達檢查都在重新啟動後才生效；目前執行中的背景工作與工作 `8149804c…` 需重新啟動後才會用新程式。
## 修正：Forge 啟動跳出「無法找到輸入點 …xformers\_C.pyd」視窗（13:00 後加入）
- 原因：`F:\forge` 的 Python 裝的是 torch 2.12 開發版（cu128，RTX 5090 需要），但 xformers 0.0.27 是為 torch 2.3.1 編譯的。Forge 本身有 `--disable-xformers`，但 Forge 的 `diffusers` 套件只要偵測到 xformers 已安裝就會自己 `import xformers.ops`，載入 `_C.pyd` 時 Windows 彈出模態錯誤視窗，啟動停在視窗上（實測 `import torch` 階段卡了 264 秒，等使用者按掉才繼續）。
- 處理（不動 `F:\forge` 內任何套件、設定或 webui-user.bat；沒有解除或升級任何套件）：
  - 新增 `workflow_v2/forge_boot.py`，由我們的啟動器以 Forge 自己的 Python 執行：(1) 設定 Windows 不為此程序彈出錯誤視窗；(2) 讓所有 import 看不到 xformers（`find_spec` 回報未安裝）；(3) 原樣執行 `launch.py`。Forge 照原本的選擇使用 PyTorch attention。
  - `local_images._spawn` 改經由 `forge_boot.py` 啟動，仍帶 `--disable-xformers`。
  - 自動啟動最多失敗 2 次就暫停：每次自動啟動都記錄在 `data/workflow-v2/image-service-state.json`；程序結束（啟動失敗）或超過 5 分鐘仍沒開 7860（例如卡在錯誤視窗，會結束該程序）各算一次失敗；連續 2 次後 6 小時內不再自動啟動，系統頁顯示中文提示並自動改用 Openverse／Wikimedia／圖解。排除問題後刪除該狀態檔即可恢復。成功啟動會把失敗次數歸零。
  - 系統頁新增「暫停自動啟動」狀態（黃色），說明原因與處理方式。
- 測試：`tests/test_forge_xformers.py`（7）：包裝程式隱藏 xformers 並轉送參數、啟動命令經過包裝程式、程序結束計一次失敗、連續兩次暫停、暫停到期與成功歸零、卡住逾時被結束、暫停時生圖直接改用授權素材且不再啟動。
- 實測：以新方式重啟 Forge，15 秒內 7860 可用（`/sdapi/v1/options` 回 sd_xl_base_1.0），沒有彈窗、日誌沒有新的 xformers 警告；512×512 測試圖 6.2 秒生成成功（`tmp\forge-test.png`）。

## 任務控制台「太空任務」遙測風格（回應「控制台太呆板、沒有 SpaceX 科技感」）
- **風格**：任務控制／發射遙測的感覺，但維持克制：圓角、細線、等寬數字；沒有外部字型或圖片（系統等寬字型 `ui-monospace` 後援）。白色預設與其他主題都保留，深色主題多了極細的線格背景與頂端一條細發光線。
- **畫面**：
  - 頂端狀態晶片：正常／待命／注意／異常（取代舊的小圓點字樣）。
  - **T+ 已經過／T− 還需要**：時:分:秒，等寬字型；還無法估算時顯示「估算中」。
  - **發射程序**：讀取教材→規劃→撰寫→審查→排版→預覽→發佈，七個圓點，完成的實心、目前這一步柔和呼吸。
  - **遙測方塊**：完成頁數（細條）、生成速度（詞元／秒）、模型負載（圓環＋最近變化的折線）、顯存（圓環＋吉位元組）。
  - **遙測訊息**：最新 3 筆、前面有等寬時間；完整紀錄仍收在「詳細資訊」。
  - **服務方塊**：工作程序、本地模型服務、本機生圖、磁碟空間，各有「正常／注意／異常」。
  - 進場淡入＋依序上滑（純 CSS）；數字用 `@property` 平滑跳動。「減少動態效果」開啟時全部關閉。
- **程式**：`console_state.py`（`hms`、`stage_track`、`speed_per_second`、`gpu_numbers`、`push_history`）、`console_view.py`（`tracker_html`、`tiles_html`、`telemetry_feed_html`、`service_tiles_html`、`sparkline`）、`console_theme.py`（`_TELEMETRY` 樣式、`--mono`／`--grid` 變數）、`monitor_ui.py`（把 `extras` 傳進卡片）。每個檔案修改前都有 `.bak-20261004-…-telemetry` 備份。
- **測試**：新增 `tests/test_console_telemetry.py`（14 項）；既有控制台測試維持通過。
- **限制**：折線是「開啟這個頁面之後，每秒一次的 GPU 使用率」，存在畫面的工作階段中，重新整理就會重新累積，不寫入磁碟；生成速度是整份工作的平均值。畫面只在無頭 Edge 用測試資料驗證過。
- **看到新畫面**：執行中的 8502 服務沒有重啟；請關閉教材AI.cmd 後再開啟教材AI.cmd。