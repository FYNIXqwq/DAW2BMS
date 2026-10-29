# Ableton Live 工程支援可行性

研究日期：2026-10-28。本文保留最初的可行性調查，後續已實作第一階段 ALS 讀取。
目前 `convert`、`extract` 和 GUI 已接受 ALS，輸出 Arrangement MIDI/JSON；
`convert --ableton-render` 和 GUI 的可選桌面渲染已支援一部分原生音源，詳見下節。
最初的讀取驗證沒有安裝或啟動 Ableton Live，也沒有使用 computer use。

## Windows 原生渲染實作驗證（0.8.0）

使用者允許 Windows GUI 自動操作後，已獨立實作 PyAutoGUI 輸入與 UIA 控件讀取。
沒有複製 AbletonBatchRender 原始碼，也沒有安裝 Remote Script。
驗證環境為 Windows、Live 12 Suite 12.4.7、簡體中文 Live UI。

- 自建 Operator 單音工程成功匯出 176400 frames、44.1 kHz、雙聲道、24-bit WAV。
- ALS 隔離單音副本、切音及 BMS 完整流程成功。
- 三個音高的獨立測試從 0.1 秒尾音探測開始，實測重試至 0.2、0.4 秒後通過。
  3 個鍵音在 BMS 中分別對應原始 tick 0、960、1920，加一小節 3840 ticks。
- 檔案/鍵音雜湊、WAV 格式/長度、靜音尾端與 BMS 事件回讀均由程式檢查。
- 桌面自動操作已隔離為子進程；PyQt6 ConversionWorker 連續兩次原生渲染與 BMS 匯出通過。
- 開發時曾因副本錯刪 GroovePool 內的 MidiClip 造成 Live 載入崩潰；已限制編輯容器，
  加入 GroovePool 原樣保留與原生 Notes 節點結構的回歸測試，修正後通過完整實測。

目前處理固定速度、4/4、可精確表示的非負 MIDI 時間，以及支援的靜態原生與 VST2/VST3 裝置鏈。
缺失／停用／掃描失敗的插件、Audio Unit、缺失樣本、動態自動化及不支援路由保留 MIDI 並警告。
這是可測試的原生渲染原型，不是任意 ALS 完整還原的宣告。使用方式與限制見 README。
以下章節保留此前研究紀錄，早期未實作或禁止 GUI 的判定不代表目前狀態。

### 外部插件與 MCP 驗證

已實測 Vital VST3 與 Vital VST2，各以三個音高完成原生離線渲染、切音與 BMS 匯出。
讀取 `Live-plugins-1.db` 的掃描結果，使用 VST2 UniqueId 或 VST3 UID，不能以顯示名稱代替 ID。
庫中的 `arch` 在本次觀察中對應 VST2=2、VST3=3，不當作 CPU 位元寬度使用。
預設及二進位狀態完整保留。載入驗證只接受本次唯一工程路徑之後的新日誌，
逐實例檢查 `Restored`，VST3 檢查 processor CID，VST2 檢查 DLL 路徑。
舊日誌、錯誤 ID、少一個實例或僅 Created 而未 Restored 都不能通過。

Live 對 Vital 的可選 audio bus deactivation 拒絕會記錄 error，但後續仍可成功恢復預設。
僅排除該已觀察的特定診斷；仍須具備所有恢復證據並通過 WAV 檢查。
未知載入/狀態錯誤仍停止音訊，保留 MIDI。

使用者另行授權安裝 AbletonMCP。已安裝 [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp)，
固定提交 `9dddc7bd5b95412510fdeb745949e3bf23f3fd8a`（server 1.4.5，Remote Script 1.7.1）。
以 uv tool 安裝至使用者工具環境，Remote Script 位於 User Library 的 `Remote Scripts/AbletonMCP`；
Codex stdio 服務名稱為 `ableton`，設定 `ABLETON_MCP_DISABLE_TELEMETRY=1`、
`ABLETON_MCP_DISABLE_DATASET=1`、`ABLETON_MCP_SKIP_SCRIPT_INSTALL=1`。
Live 控制介面第一列選擇 AbletonMCP，Input/Output 均為 None；握手實測版本一致，
並成功查詢裝置、以精確 URI 載入 VST2、建立 MIDI 和 Arrangement 測試片段。
橋接只綁定 localhost:9877。它不取代原生離線匯出；原生/VST 路徑不依賴它，後續的 Max 路徑使用其 Remote Script 驗證狀態。

### Max for Live 實作驗證（2026-10-29）

已支援 `MxDeviceInstrument`、`MxDeviceMidiEffect`、`MxDeviceAudioEffect`。
原先僅拒絕 `MxDevice` 的條件未涵蓋這三種實際節點，本次統一識別 Max 節點並強制驗證，避免未驗證的旁路輸出。
從 `PatchSlot/Value/MxPatchRef/FileRef` 解析 `.amxd`，並處理 FileDropList 的顯式依賴。
保留 ParameterList、BlobSlot 與其他不透明狀態，只在生成副本中重定位路徑。

Live 的 Max 裝置沒有可直接使用的通用「載入成功」公開旗標；`is_active` 僅表示開關狀態。
因此使用已安裝 AbletonMCP 的本機唯讀快照，核對生成片段名稱、裝置的軌道/鏈位置、類型及已儲存參數，
連續兩次一致後再匯出。XML 的 Index 包含 Max 隱藏控制項，與 Live 公開參數索引不同；
按 Timeable 子集的順序及長/短名稱核對，不以相同顯示名稱隨意配對。
依賴檔案哈希和本次工程載入後的 Max 錯誤記錄在渲染前後檢查。

DS Kick 單獨的三音測試已完成；Note Echo → DS Kick → Envelope Follower 三類裝置串接亦通過，
回聲尾音觸發自適應重試後完成三鍵音與 BMS。測試工程與音訊僅存於忽略目錄。
缺失 AMXD 的混合工程實測保留 3 個 fallback MIDI 音符，可用 Max 軌道仍輸出 3 個鍵音，
報告標記 `audio_complete=false`。鏈路與混合測試譜均通過獨立 BMS 解析器驗證，時間誤差為零。
這不宣稱能模擬任意 Max 補丁；跨設備映射、非標準路由、無法驗證的參數狀態會保留 MIDI。
未在 ALS 列出的動態外部依賴仍由 Max 負責載入，若錯誤只出現在 Max Console，通用驗證不能保證察覺。

來源：[MaxDevice API](https://docs.cycling74.com/apiref/lom/maxdevice/)、
[Device API](https://docs.cycling74.com/apiref/lom/device/)、
[Max 依賴封裝](https://docs.cycling74.com/userguide/m4l/live_sharing/)。

## AbletonBatchRender 源碼調查與 Windows 適配方向

2026-10-28：使用者後續允許 Windows GUI 自動化，指定 PyAutoGUI，並提出研究
[deaddropsec/AbletonBatchRender](https://github.com/deaddropsec/AbletonBatchRender)。
本節取代下節中「介面自動化不作為採用路線」的早期限制；產品目前仍未實作 ALS 音訊渲染。

檢查版本：`be1ed5195d7121ecba26edb481acfb22df570ada`。研究副本位於 Git 忽略的
`.scratch/AbletonBatchRender/`。本次為靜態源碼檢查，未安裝其 Remote Script、執行其自動化，
也未完成本機 Windows 的實際渲染測試。

**結論：可借鑑其流程分工，但不能直接作為 Windows 渲染後端或完整鍵音轉換器。**

### 實際流程

1. 解析 ALS 中 Arrangement 的片段結束位置，可搜尋並重定位缺失的音訊素材。
2. 使用 macOS `open` 載入工程，透過 Remote Script 的 `song.file_path` 查詢載入狀態。
3. Remote Script 在本機 TCP 埠提供工程、循環範圍及對話框資訊。
4. JXA/`osascript` 傳送 Cmd+Shift+R 和 Enter，操作原生 Export Audio/Video 與儲存窗口。
5. 輪詢狀態並選擇性檢查輸出檔案。

它使用 Live 原生離線匯出；Remote Script 本身沒有提供直接渲染函式。
README 要求 macOS、Live 12 Suite、Python 3.11+，還要求預先配置匯出格式與目錄。
`--export-dir` 只指定驗證目錄，並不設定 Live 的輸出位置。

### 與 DAW2BMS 需求的差距

| 項目 | 源碼觀察 | DAW2BMS 適配要求 |
| --- | --- | --- |
| Windows 操作 | `automation.py`、`keystroke.py`、`project_loader.py` 依賴 macOS | 以 PyAutoGUI 實作操作，發送輸入前確認 Live 的前景窗口與預期對話框 |
| 逐音鍵音 | 批次匯出整個工程，沒有音符隔離、逐音切割或 BMS 對應 | 另建隔離音符工程副本與鍵音 manifest，保留裝置與路由，接回切音/BMS 管線 |
| 尾音 | `render_pipeline.py` 固定 `PADDING_BARS = 2` | 沿用逐鍵音尾音檢測與有上限的自適應重試，不固定追加秒數或小節數 |
| 缺失外掛 | README 明示可能停在缺失外掛對話框；沒有 MIDI fallback | MIDI 先落盤，缺失或無法確認的音源保留 MIDI 並警告，不能把未驗證音訊當成功鍵音 |
| 工程載入 | `project_loader.py` 確認路徑超時後仍繼續 | 必須確認是本次生成的工程副本，否則中止音訊階段 |
| 匯出設定 | 沿用 Live 上次設定，連續 Enter 確認 | 明確設定並讀回範圍、Main 輸出、PCM 格式、取樣率、正規化與循環等設定 |
| 完成狀態 | `assume_started=True` 時第一次 IDLE 即可成功；socket 超時也被視為渲染中 | 狀態僅作輔助，必須驗證本次新建 WAV 的完整可讀性、格式、長度與音訊資料 |
| 結果驗證 | `_verify_export` 只檢查同名檔案存在，且可略過 | 每次使用獨立輸出目錄，拒絕舊檔、空檔、未完成或不符範圍的音訊 |
| 彈窗 | 未知對話框按 Enter，儲存提示嘗試按 n | 未知彈窗停止並回報；不丟棄使用者原工程的未儲存修改 |

README 說不處理覆寫確認，但該版本 `wait_for_sheet_and_confirm()` 實際會對偵測到的
sheet 發送 Enter。應以核對後的源碼行為為準，不能直接沿用 README 的安全假設。

Remote Script 的 `_get_status()` 把任何非空對話框訊息歸為 RENDERING，
也把有對話框數量的狀態歸為 EXPORT_DIALOG；這不能區分缺失外掛或其他錯誤。
它在 Live 主執行緒輪詢，離線匯出期間可能失去回應，因此不能保證連續進度資訊。
原專案測試包含 mock TCP 與 mock 按鍵測試，不能替代 Windows Live 12.4.7 的端到端驗證。

### 後續實作與驗收

適配方向是 PyAutoGUI 操作原生窗口，必要時以獨立實作的窄介面 Remote Script 輔助查詢狀態。
目前檢查的 Git tree 與 pyproject 未見 LICENSE／授權宣告；本次未將其程式碼複製進產品。
保留既有 ALS reader、MIDI 匯出與切音邏輯，不引入此專案作為執行依賴。

先以自建短工程驗證原生離線 WAV 匯出，再驗證隔離音符、尾音和 BMS 時間對應。
驗收需包含：成功匯出、缺失音源、未知彈窗、使用者取消、前景切換、載入失敗、
舊檔或損壞 WAV，以及來源工程雜湊不變。完成前 ALS 仍維持 MIDI-only。

來源：
- [README（固定版本）](https://github.com/deaddropsec/AbletonBatchRender/blob/be1ed5195d7121ecba26edb481acfb22df570ada/README.md)
- [匯出流程](https://github.com/deaddropsec/AbletonBatchRender/blob/be1ed5195d7121ecba26edb481acfb22df570ada/src/render_pipeline.py)
- [狀態監測](https://github.com/deaddropsec/AbletonBatchRender/blob/be1ed5195d7121ecba26edb481acfb22df570ada/src/tcp_client.py)
- [Live 內部橋接](https://github.com/deaddropsec/AbletonBatchRender/blob/be1ed5195d7121ecba26edb481acfb22df570ada/remote_script/RenderMonitor/render_monitor.py)
- [彈窗處理](https://github.com/deaddropsec/AbletonBatchRender/blob/be1ed5195d7121ecba26edb481acfb22df570ada/src/dialog_handler.py)

## 已安裝 Live 後的全自動離線渲染調查（早期條件）

2026-10-28 再次檢查：本機已安裝 **Ableton Live 12 Suite 12.4.7**，
執行檔位於 `C:\ProgramData\Ableton\Live 12 Suite\Program\Ableton Live 12 Suite.exe`。
使用者明確要求「必須全自動離線渲染，先確認是否可行」，不接受手動匯出或即時錄製作為替代。
本次僅讀取安裝資訊、程式資源目錄與文件；沒有修改 Live 偏好、安裝 Remote Script 或操作介面。

**判定：目前沒有找到可在既有公開 API／CLI 上實作、且符合條件的可靠路徑。**
安裝 Live 提供了音訊引擎，卻不等於提供可由外部程式呼叫的離線匯出入口。

| 路線 | 本次確認 | 是否符合本次條件 |
| --- | --- | --- |
| Live 原生離線匯出 | 官方文件透過 Export Audio/Video 對話框啟動 | 缺少已驗證的無介面觸發入口 |
| Live Object Model / Remote Script | 可控制音符、播放、路由等；公開 Song/Track 函式清單未提供完整音訊匯出呼叫 | 未找到符合條件的實作 |
| Remote Script Resampling | 可用播放與錄製建立音訊 | 是即時錄製，不符合離線要求 |
| 自動操作匯出對話框 | 部分第三方工具用這種方式觸發離線匯出 | 依賴介面自動化，不作為此次採用路線 |
| 獨立 VST 宿主或自製 DSP | 可對適配的外掛／素材實作離線處理 | 不能視為完整還原 Live 原生裝置與工程 |

查閱的第三方專案 [elleural/ableton-mcp](https://github.com/elleural/ableton-mcp#limits-of-lives-api)
明確區分：其 `bounce` 是即時 Resampling；`export_audio` 則操作 Live 的匯出對話框。
它不能作為「已有無介面離線匯出 API」的證據。

本機 Program 目錄列出的執行檔為 Live、InstallHelper、Push2DisplayProcess、Push3；
沒有發現獨立渲染工具。Python 資源主要是應用程式輔助模組，未發現可直接採用的渲染 CLI。
這些是觀察結果，不是對所有未公開入口的窮盡證明；本次也未偽造命令列參數或宣稱完成實際離線渲染測試。

因此現有 ALS MIDI-only 行為維持不變。若要改變此判定，需要可重現的離線匯出介面及其測試，
至少涵蓋：載入工程副本、保留原生/VST 音源狀態、指定範圍/格式/輸出路徑、取得完成狀態與錯誤、
無人工介面操作地產生 WAV。未達成之前，不將 Ableton 安裝偵測等同於完整渲染支援。

## 第一階段實作狀態

實作位於 `daw2bms/als.py`、`daw2bms/als_export.py`，詳見 README 的 ALS 章節。
已涵蓋明確的編曲容器、循環/裁剪、靜態啟用狀態、精確拍位置、MIDI 解析度與前置負拍偏移。
公開樣本經獨立 MIDI 解析器驗證，輸出 5506 個音符與 17 個拍號事件，未修改來源。
速度自動化、Groove、MPE 與裝置處理保留資料並告警，不宣稱已模擬 Live 播放。

## 結論

不安裝 Live 仍可實作 `.als` 結構讀取、Arrangement MIDI 時間軸與 MIDI-only 匯出。
完整的獨立鍵音 BMS 另外需要可用音訊：已有獨立鍵音、可確認語義的音訊素材，或可重現原工程的渲染環境。
不能把讀懂 XML 等同於能執行 Live 內建裝置、Max for Live 或還原所有效果器處理。

| 工作 | 未安裝 Live 時的可行性 |
| --- | --- |
| 解壓與讀取 ALS | 可以；實測為 gzip 壓縮的 XML |
| 讀取軌道、片段、MIDI 音符、素材與裝置引用 | 可以；需按版本和容器區分 |
| 還原 Arrangement 中的 MIDI 配置 | 可以開發；必須處理來源偏移、循環與邊界 |
| 將 Session View 自動當成完整歌曲 | 不可直接假設；片段可由使用者以任意次序觸發 |
| 匯出 MIDI 與 JSON | 可以；與現有缺失音源時保留 MIDI 的政策一致 |
| 從現有音訊產生 BMS | 視素材而定；必須處理或拒絕 Warp、裁剪、淡入淡出及效果鏈等情況 |
| 原生音源、效果器的可靠渲染 | 不能只靠 ALS 解析完成 |
| 直接套用 FL 的命令列批次渲染方式 | 尚未確認 Live 有等價介面，不應承諾 |

## 本次離線實驗

讀取來源：[pyableton 公開測試工程](https://github.com/maranedah/pyableton/blob/main/test/test.als)。
研究下載與統計只保留在被 Git 忽略的 `.scratch/ableton-research/`；不把外部工程納入產品或測試依賴。
未執行該專案的音源，也未執行下載的第三方程式。

| 項目 | 實測結果 |
| --- | --- |
| Creator | Ableton Live 11.1.5 |
| 格式版本欄位 | MajorVersion=5，MinorVersion=11.0_436 |
| 壓縮檔大小 | 213314 bytes |
| XML 大小 | 3236519 bytes |
| MidiTrack / ReturnTrack | 4 / 2 |
| Arrangement MIDI 片段 | 4 |
| 原始 MidiNoteEvent 記錄 | 5506 |
| AudioClip | 0 |
| FileRef | 167；引用數不等於實際音訊檔案數 |
| Tempo/Manual | 180；僅是儲存值，未驗證整曲是否恆速 |

觀察到的編曲片段位置：

```text
Ableton/LiveSet/Tracks/MidiTrack/DeviceChain/MainSequencer/
ClipTimeable/ArrangerAutomation/Events/MidiClip
```

音符記錄有 Time、Duration、Velocity、OffVelocity、Probability、IsEnabled、NoteId 等屬性。
音高由 KeyTrack 層級提供，不能只掃描 MidiNoteEvent 就忽略它的父層。
該檔案含循環片段，例如片段長度與 LoopStart/LoopEnd 範圍不同。
5506 是原始儲存記錄數，**不是已展開或已驗證的實際發聲音符數**。

本次只證實 gzip/XML 可讀與上述欄位可取得，尚未在 Live 中對照播放、裁剪、循環或音訊渲染。
一個 Live 11 樣本不能作為全部 Live 版本的相容性保證。

## 第一階段建議範圍

1. 加入獨立的 ALS reader，讓 `.flp` / `.als` 經過不同讀取器，再進入共用事件模型。
2. 首先支援 Arrangement View 的 MIDI 軌道；Session 片段另列清單，不虛構播放順序。
3. 保留片段起訖、StartRelative、LoopStart/LoopEnd/LoopOn、停用狀態及原始音符屬性。
4. 正確展開循環並限制在片段邊界；不支援的語義應明確診斷，不能悄悄漏音。
5. 未安裝 Live 或沒有可用鍵音時，匯出 MIDI/JSON 並警告；不要產生看似完整的空白有聲譜。
6. 使用合成 XML/gzip 夾具與外部可選測試路徑，不在程式碼中固定示例檔名、數量或時間位置。
7. 新警告與 GUI 文案沿用現有 zh-TW / en / ja / ko 語言資源。

### 時間模型

ALS 中以拍為單位的數值需要保留十進位／有理數精度，不應套用 FL 的原始 PPQ，
也不應假裝 Ableton 檔案天生就有某個固定 MIDI PPQ。
匯出 MIDI/BMS 時再依所需精度選擇整數解析度；無法精確表示時要告知限制。
首版可限制固定 BPM / 4/4；速度與拍號自動化需偵測並保留，不能把 Tempo/Manual 當成完整速度曲線。

### 音訊與裝置

- `.als` 是 Live Set；完整 Live Project 還可能包含 Samples、裝置及其他素材。
- Collect All and Save 有助於收集引用素材，但不等於打包外掛執行檔或授權。
- 已有 Freeze/Bounce 音訊可能有用，但不是天然的逐音鍵音：可能包含和弦、重疊尾音和處理結果。
- Live 12 的 Bounce 文件指出它是 post-FX / pre-mixer；音量、聲像與 sends 留在軌道設定，
  因此不能把取得的音訊直接當作完整原曲混音。
- Warp 的 BeatTime/SecTime、拉伸模式、clip envelope、音高變更和淡入淡出需要獨立處理。
- 缺失／無法還原的音源仍保留 MIDI。音訊軌若沒有音符資料，不能憑空轉出 MIDI 音符。

## 渲染介面調查

官方文件說明了 Export Audio/Video 與 Bounce 工作流程；本次查看的 Live Object Model Song
介面沒有找到可直接取代 FL `/R` 的整曲音訊匯出呼叫。
這是目前未確認的能力，不能據此斷言所有版本都不存在其他介面。
後續若要做全自動渲染，仍需要單獨驗證版本、介面、音源及背景執行行為；不能依靠未經確認的 CLI 參數。

## 主要來源

- [Ableton：Live Concepts](https://www.ableton.com/en/manual/live-concepts/) — Arrangement 與 Session 的角色與播放方式。
- [Ableton：Arrangement View](https://www.ableton.com/en/manual/arrangement-view/) — 線性編曲、片段位置與裁剪。
- [Ableton：Managing Files and Sets](https://www.ableton.com/en/manual/managing-files-and-sets/) — Live Set、Project、素材收集與音訊匯出。
- [Ableton：Bounce to Audio](https://www.ableton.com/en/live-manual/12/bounce-to-audio/) — 渲染階段與原混音的差異。
- [Cycling '74：Song / Live Object Model](https://docs.cycling74.com/apiref/lom/song/) — 公開的 Song 操作介面。
- [pyableton](https://github.com/maranedah/pyableton) — 已有獨立 ALS 解析及 MIDI 匯出的先例；本次使用其公開樣本做格式探測，未納入為執行依賴。
