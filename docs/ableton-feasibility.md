# Ableton Live 工程支援可行性

研究日期：2026-10-28。本文保留最初的可行性調查，後續已實作第一階段 ALS 讀取。
目前 `convert`、`extract` 和 GUI 已接受 ALS，輸出 Arrangement MIDI/JSON；音源渲染仍未實作。
沒有安裝或啟動 Ableton Live，也沒有使用 computer use。

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
