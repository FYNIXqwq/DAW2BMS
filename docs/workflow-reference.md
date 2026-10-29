# DAW2BMS 工作流与技术参考

安装与日常使用请先阅读 [项目 README](../README.md)。本文保留各阶段命令、数据约定、验证记录和格式边界；命令示例从项目根目录运行。

将 DAW 工程的音乐结构提取为可用于后续 BMS 制作的中间数据。
当前版本支持 **FLP 结构提取、独立键音工程生成、FL 命令行渲染、WAV 切音和 BMS 测试谱导出**，
以及 **Ableton ALS Arrangement 读取、MIDI 导出和 Windows 原生离线渲染/BMS 测试谱**。
遇到缺失资源的通道会保留 MIDI 并在命令行警告，其他可用通道继续处理。
输入 FLP/ALS 始终只读，改动仅发生在新建的采样工程副本中。FL 使用命令行渲染；
Ableton 可选使用 PyAutoGUI 操作原生导出窗口。

## 运行

需要 Python 3.10 或更新版本。结构提取、MIDI 导出和工程准备只用 Python 标准库，无须 PyFLP。
音频渲染需要本机 FL Studio 及可用的音源；WAV 校验/切分使用可选 `audio` 依赖。

## BMSE Wails 3 集成

BMSE 的 Wails 3 重写版已通过 `python -u -m daw2bms.bridge` 复用此引擎。
宿主在 stdin 写入单行 JSON 请求，stdout 返回 protocol 1 的 JSON-lines 事件：
`hello`、`tracks`、`progress`、`result`、`cancelled` 或 `error`。
分析只读工程，不启动 DAW；转换必须提供分析得到的 `source_sha256`，防止旧轨道选择用于已修改的工程。
宿主保留 stdin，发送 `{"action":"cancel"}` 可请求协作式停止；stdin 断开也会请求停止。
引擎返回完整输出目录与相对谱面路径，BMSE 在处理未保存确认后读取生成 BMS，保留音频相对路径继续编辑。

此接口不需要 PyQt6，不监听网络端口。BMSE 的 Python/引擎位置可配置，示例工程不属于接口依赖。
原 CLI 与下方独立 PyQt6 界面保持可用。

## PyQt6 桌面界面

安装 GUI 及音频依赖后启动：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
.\.venv\Scripts\python.exe -m daw2bms gui
```

也可以运行安装后生成的 `daw2bms-gui`，或使用 `python -m daw2bms.gui`。
可选传入工程路径以预填文件框，不会自动开始转换：

```powershell
.\.venv\Scripts\python.exe -m daw2bms gui "D:\YourProjects\song.flp"
```

- 支持繁體中文、English、日本語、한국어的单窗口，中性深灰界面，少量蓝色强调。左侧选择或拖入 FLP/ALS、选择输出父目录；右侧查看进度、日志和警告。
- 选择文件后读取音轨，在右侧“谱面音轨”页签逐轨选择按键音符、BGM 或不导出。手动填写路径后可点击“读取音轨”。
  GUI 默认将可用轨道设为 BGM；“全部设为按键”可恢复全音符测试谱。左侧实时汇总三种用途的轨道数。
- 选择 ALS 后，默认只导出 MIDI。在高级设置勾选“使用 Ableton 渲染 ALS（会操作桌面）”后启用音频/BMS 参数。
  此选项每次启动默认关闭；需要安装下文的 `ableton` 依赖。可指定 Live 路径或自动检测。
- 高级设置提供 FL 路径、额外素材目录、谱面标题/作者、准备小节、尾音探测和重试上限、超时、键音复用。
- 调用同一个 `convert` 后端，在 QThread 中运行。不会阻塞窗口，也不允许同时重复启动转换。
- 进度按真实阶段/重试轮次显示，运行期间为不定进度，不编造完成百分比。
- 缺失插件继续保留 MIDI；完成、部分音源缺失、MIDI-only、失败和停止分别显示，只有实际存在的结果才可打开。
- “停止后续步骤”是协作式停止：等待本次 FL 渲染/切音操作结束，再停止后续工作并保留已有文件。
  不强制终止 Qt 线程或其他 FL 进程。运行期间关闭窗口会被拦截；停止完成后可正常退出。
- `Ctrl+O` 选择工程，`Ctrl+Enter` 开始转换。支持保存日志、打开输出目录、谱面目录、MIDI 和报告。
- 记住上次工程、输出父目录和 FL 路径；偏好通过 Qt 的用户级设置存储，测试使用隔离的临时设置文件。

GUI 主动停止时 `conversion.json` 记录 `cancelled`。CLI 的原有结果状态不变。
开发测试使用 Qt offscreen 和应用自身的 widget 渲染，不使用 computer use 或操作其他软件界面：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_gui.py -v
.\.venv\Scripts\python.exe tests\render_gui_preview.py --out output\gui-preview
```

## 語言與 i18n

命令列與 GUI 均支援 `zh-TW`、`en`、`ja`、`ko`。**未手動設定時，預設跟隨作業系統的介面語言**；
Windows 透過 `GetUserDefaultUILanguage` 讀取使用者介面語言，不使用日期／數字格式地區來猜測。
中文語系對應繁體中文，日文與韓文對應各自語言，其他不支援的系統語言回退至英文。

命令列的選擇順序：`--lang` → `DAW2BMS_LANG` 環境變數 → 系統語言。
`--lang` 可放在子命令前後，命令名稱、選項名稱和資料格式保持不變：

```powershell
.\.venv\Scripts\python.exe -m daw2bms --lang zh-TW convert "D:\YourProjects\song.flp"
.\.venv\Scripts\python.exe -m daw2bms convert "D:\YourProjects\song.flp" --lang en
.\.venv\Scripts\python.exe -m daw2bms --lang ja --help
.\.venv\Scripts\python.exe -m daw2bms gui --lang ko
```

GUI 右上方可隨時切換語言，手動選擇會記憶；選擇「跟隨系統」可恢復自動選擇。
GUI 啟動時的優先順序是：當次 `--lang` → `DAW2BMS_LANG` → 已儲存的選擇 → 系統語言。
執行中切換只更新文案和記錄的顯示，不會重啟工作、清空輸入或更改音訊參數。
已產生的檔案不會因切換語言而重寫；背景工作產生的文字說明使用工作開始時的語言。

說明、進度、警告、應用程式錯誤、GUI 文案及文字報告共用 `daw2bms/locales/*.json`。
背景訊息保留英文原始模板與具型別的參數，顯示時才翻譯，因此進度辨識不依賴譯文。
JSON 欄位、狀態碼、診斷碼、命令參數、外掛名稱、使用者路徑與譜面中繼資料保持原樣。
作業系統、第三方套件的原始錯誤與 traceback 仍保留原文，避免錯誤翻譯診斷內容。
個別翻譯缺漏時使用英文回退；未知語言的 `--lang` 會明確報錯。

語言測試涵蓋目錄完整性、占位符一致性、系統語言／手動覆寫、命令列說明和錯誤、
四語 MIDI 降級、執行中 GUI 切換，以及中日韓路徑保留：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_i18n.py -v
.\.venv\Scripts\python.exe tests\render_gui_preview.py --out output\gui-ja --lang ja
```

## 一条命令生成谱面

首次安装依赖（已有 `.venv` 时无须重建）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[audio]"
```

之后只需要输入工程路径：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\YourProjects\song.flp"
```

对于 FLP，命令依次读取工程、检查资源、生成采样副本、自适应渲染/切音并导出 BMS。
对于 ALS，默认读取 Arrangement 并直接导出 MIDI/JSON；添加 `--ableton-render` 可通过 Windows Live 离线渲染键音并导出 BMS。
不依赖特定示例文件，不会修改原工程。
默认输出到当前目录的 `output/<工程名>-bms/`；目录已存在时自动使用 `-2`、`-3` 等后缀。
使用 `--out <新目录>` 可以指定输出位置，显式指定的已有目录不会被覆盖。

### 选择哪些轨道变成按键

FLP 按 **Playlist 音轨 ID** 选择，不是 Channel Rack 或 Mixer ID。
同一个音源、同一个 Pattern 放在不同 Playlist 音轨上，可以分别成为按键或 BGM。
ALS 使用 Arrangement 轨道 ID。

| 用途 | 导出行为 |
| --- | --- |
| 按键音符 | 分配到可演奏的 BMS 键道；同一时刻超过 7 键的部分仍进入 BGM |
| BGM | 保留声音，按原始时间在 BMS `01` 通道自动播放，不占用按键 |
| 不导出 | 在采样前排除该音轨的音符，不写入本次音频及 MIDI |

先查看当前工程的真实轨道 ID，再选择需要击打的轨道：

```powershell
python -m daw2bms tracks "D:\Projects\song.flp"
python -m daw2bms convert "D:\Projects\song.flp" --play-tracks 1,5 --exclude-tracks 4
python -m daw2bms convert "D:\Projects\song.als" --ableton-render --play-tracks 7,12
```

指定 `--play-tracks` 后，其他未排除轨道作为 BGM。`--play-tracks none` 可导出纯 BGM 测试包，程序会提示没有按键音符。
为兼容旧脚本，CLI 不传 `--play-tracks` 时仍将全部所选音符视为按键候选。
`--play-channels` 的旧音源通道筛选仍可使用；与 `--play-tracks` 同时指定时，只有两者交集成为按键。

已有完整键音包时，可以快速重选按键/BGM，不必重新渲染：

```powershell
python -m daw2bms bms ".\output\song-bms\work\keysounds" --out ".\output\chart-v2" --play-tracks 2,5
```

GUI 支持选择 FL Arrangement、异步读取轨道、批量设置按键/BGM，以及四语切换。
未命名的 FL 音轨会用其音源名称辅助辨识，原工程不改名。
同一文件刷新保留角色选择，切换编曲时各自保留选择；文件内容改变后需重新读取，不能沿用旧轨道分配直接转换。
`conversion.json` 的 `track_roles` 记录本次选择，`chart/mapping.json` 保留每个音符的原始音轨、位置及按键/BGM 原因。

这一版 BGM 沿用独立键音生成与自动播放，**尚不是原编曲的整轨伴奏渲染**，仍受隔离音符的效果/自动化限制。
音频片段、无法解析的片段或静音轨道在 GUI 中默认排除并锁定；当前不会将这些音频素材自动合成为 BGM。
缺失音源的所选轨道仍保留 MIDI 并警告；即使全部按键轨道缺失，其他可用 BGM 也可以正常导出。

FL Studio 查找顺序：`--fl-exe` → 环境变量 `DAW2BMS_FL_EXE` → 默认安装目录中目录版本号最高的 FL Studio → PATH 中的 `FL64.exe`。
自定义安装位置示例：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\YourProjects\song.flp" --fl-exe "D:\Apps\FL Studio\FL64.exe" --out .\output\MySong
```

输出结构：

```text
<工程名>-bms/
  chart/test.bme            播放器测试谱
  chart/audio/*.wav        谱面使用的独立键音
  chart/mapping.json       键音与原曲时间轴的映射
  song.mid                 本次选择的完整 MIDI
  fallback.mid             缺失音源的 MIDI（有缺失时）
  fallback_notes.json      缺失音符及资源信息（有缺失时）
  project.json             FLP 提取结构
  conversion.json          总流程状态、警告、结果路径
  work/                    采样工程、渲染和自适应重试记录
```

将 `chart/` 整个文件夹加入播放器曲库，建议先用 AUTO PLAY 检查。
缺失插件继续保留 MIDI 并向命令行 stderr 输出 `WARNING`；其余可用音源继续生成谱面。
如果全部音源不可用、缺失效果器使音频降级，或未找到 FL Studio，结果为 `midi_only`，
保留 MIDI/JSON 并跳过 BMS，避免生成看似成功但没有声音的空谱。
渲染超时或校验失败时以错误退出，`conversion.json` 记录失败阶段，已生成的 MIDI 仍会保留。

`conversion.json` 的 `status`：`complete` 表示谱面已导出；`midi_only` 表示只有 MIDI；`error` 表示流程失败。
前两者命令退出码为 0，失败为 1；`complete` 时仍应检查 `audio_complete` 和警告，缺失通道不会被伪造为键音。

高级参数沿用分步流程：`--channels`、`--midi-only`、`--resource-dir`、`--arrangement`、
`--initial-tail`、`--max-tail`、`--max-attempts`、`--timeout`、`--no-dedupe`、
`--title`、`--artist`、`--lead-in-bars`、`--play-channels`、`--encoding`。
不传标题/作者时使用工程元数据，未设置则使用工程文件名和 `Unknown`。

## Ableton ALS：Arrangement、MIDI 与可选原生渲染

Windows 安装渲染依赖并转换：

```powershell
python -m pip install -e ".[gui,ableton]"
python -m daw2bms convert "D:\Projects\song.als" --ableton-render
# 自定义 Live 安装位置：
python -m daw2bms convert "D:\Projects\song.als" --ableton-render --ableton-exe "D:\Apps\Live\Program\Ableton Live 12 Suite.exe"
```

查找顺序：`--ableton-exe` → `DAW2BMS_ABLETON_EXE` → ProgramData 下的 Live 安装目录。
GUI 使用相同后端；界面语言继续跟随操作系统或手动选择。

此后端需要可交互的 Windows 桌面，**音频由 Live 原生离线导出**。运行前保存当前 Set，
运行期间保持 Live 在前景。PyAutoGUI 发送点击/按键，pywinauto 仅通过 UI Automation 读取控件位置和值；
不写死屏幕坐标，不安装 Remote Script。将鼠标移到主屏幕角落可触发 PyAutoGUI 停止。
桌面操作在独立辅助进程中执行，避免 COM 状态跨 GUI 工作线程残留；停止只终止辅助进程，不强杀 Live。
未知窗口、焦点切换或超时会停止自动操作并保留 MIDI，不会自动丢弃未保存工程或确认覆盖。

流程：先保存 `song.mid` → 对可支持轨道生成独立音符 ALS 副本 → 自动打开并导出 Main 音频 →
校验新 WAV 的完整性、时长和格式 → 逐键音检测尾音并自适应重试 → 导出 7-key BMS。
原始位置写入 `chart/mapping.json`，BMS 只增加配置的准备小节。
导出设置为 44.1 kHz、双声道、24-bit WAV，关闭标准化、循环渲染、抖动、MP3 和视频。
每次重试使用新的工程名和目录；完整记录保存在 `work/track-*/attempt-*/`，不会接受已有 WAV 为新结果。

**当前支持边界**：

- 已在本机 Live 12 Suite 12.4.7 的简体中文界面验证 Operator、Vital VST2/VST3、多个音高、自动尾音重试、BMS 时间映射及 GUI 工作线程连续两次转换。
  控件按结构识别；其他 Live 版本和语言界面仍需要实机验证，不识别时停止。
- 支持固定速度、4/4、可精确表示的非负 Arrangement MIDI 时间，以及原生和 VST2/VST3 静态装置链。
  保留该轨道、返送和 Main 的装置状态；独立音符相加不保证重现压缩、连奏等依赖上下文的混音。
- VST2/VST3 使用 Live 的只读扫描数据库按 UniqueId/UID 匹配，保留原始预设、处理器/控制器状态与参数；不按名称替换插件，也不跨格式迁移预设。
  轨道、嵌套 Rack、返送和 Main 的插件均检查。缺失、禁用、扫描失败或模块文件不存在时，该轨道保留 MIDI，其他可用轨道继续。
  每次载入副本后必须取得本次 Live 日志中的插件实例及预设恢复证据；VST3 还检查 CID，VST2 检查模块路径。
  不能确认时停止音频阶段，避免把缺失效果器的旁路音频当作成功。`render_receipt.json` 保存验证结果。
- 请先在 Live 设置中启用所需 VST2/VST3 目录并完成扫描。转换器不自动改动这些设置；仅安装插件文件不够。
  插件自带的授权、素材库或弹窗仍可能阻止载入。内部素材若由插件自行替换且不报告，通用检查无法保证察觉。
- 缺失素材、没有音源、Audio Unit，以及群组/跨轨路由、自动化、Groove、MPE、随机音符和裁剪语义均保留 MIDI 并警告。
- Arrangement 音频片段仍只记录，不转换为键音；存在此类片段时不会声称音频完整。
- 音频检测失败的键音保留 MIDI。可预先识别的不可用轨道不会阻塞其他轨道；未知 Live 弹窗会终止后续界面操作。
- `--channels`、`--midi-only` 使用 ALS MIDI 轨道 ID；尾音参数、`--no-dedupe`、谱面元数据、准备小节与编码可用于渲染模式。

开发验证可选使用 [AbletonMCP](https://github.com/ahujasid/ableton-mcp) 查询设备、加载插件与创建测试 MIDI。
本次使用 server 1.4.5 / Remote Script 1.7.1，固定上游提交 `9dddc7bd5b95412510fdeb745949e3bf23f3fd8a`。
普通原生音源和 VST 渲染不依赖它；Max for Live 的运行时验证需要 Live 内的 Remote Script。
离线 WAV 导出仍由原生窗口完成。MCP 安装与连接记录见 `docs/ableton-feasibility.md`。

### Max for Live

同一个 `--ableton-render` 命令和 GUI 选项支持 Max 乐器、MIDI 效果器与音频效果器。
已在 Live 12.4.7 实测 DS Kick，以及 Note Echo → DS Kick → Envelope Follower 的完整链路和尾音自适应重试。

- 在 Live 控制介面启用 AbletonMCP Remote Script（已验证 1.7.1 / snapshot v2，Input/Output 均为 None）。
  转换器只通过 localhost:9877 查询脚本能力和设备快照，无须运行 Codex 或 MCP 客户端。
- 从 `.amxd` 引用和 FileDropList 检查文件，支持绝对路径、项目相对路径、内置设备目录及 `--resource-dir`。
  歧义路径、无效设备、缺失设备或显式引用的素材会让对应轨道保留 MIDI 并警告，其他可用轨道继续。
  原始 ALS 和 AMXD 只读；副本只重定位文件引用，保留参数、Blob 和设备链顺序。
- 原生导出前，通过桥接读回正确轨道/嵌套链位置的设备类型、名称、开关和已保存的可自动化参数，
  连续两次核对一致才继续。同时检查本次工程的 Max 错误日志，并在导出前后验证依赖文件哈希。
  检查结果保存在 `render_receipt.json` 的 `max_load` 中。
- 跨设备映射/额外路由、没有可验证保存参数或无法读回状态的设备会保留 MIDI。
  Max 的内部变量、动态脚本依赖和外部对象并不都暴露给 Live API；仅在 Max Console 内报告的错误无法保证被通用检查发现。
  使用 Max 的 Freeze Device 封装依赖有助于工程转移，它与 Freeze Track 不同。
- 依赖播放位置、实时输入、随机状态或控制其他设备的补丁，不能保证通过隔离音符重现原曲行为。
  MIDI 效果器生成的回声等声音包含在键音内，BMS 仍按原始输入 MIDI 的时间放置按键。

参考：[Max for Live 设备及依赖说明](https://www.ableton.com/en/manual/max-for-live/)。

纯 MIDI 模式无需安装或启动 Live：

支持 gzip 压缩的 `.als` 和 UTF-8 明文 XML 形式；不需要安装 Ableton Live，也不需要音频依赖。
文件选择、拖放、进度及警告均已接入 CLI/GUI 和四种语言：

```powershell
# 默认创建 output/<工程名>-bms/，重名时自动编号；本阶段不生成有声 BMS。
python -m daw2bms convert "D:\Projects\song.als"

# 只读提取；ALS 同时写出 Arrangement MIDI。
python -m daw2bms extract "D:\Projects\song.als" --out .\output\ALS-inspect
```

输出包括 `project.json`、`clips.csv`、`notes.csv`、`timeline_notes.csv`、`song.mid`、`fallback.mid`、
`fallback_notes.json`、`midi_mapping.json`、`summary.txt` 和 `conversion.json`。
未启用 `--ableton-render` 时，`conversion.json` 中 `daw=ableton_live`、`status=midi_only`、`rendering=disabled`，且 `chart=null`。
启用时记录 `rendering=pyautogui`；只有成功验证的键音才进入 BMS。没有可用音频时保留 MIDI，不生成空白有声谱。
`--channels` 可按 ALS MIDI 轨道 ID 筛选导出的 MIDI；ALS 只有一个线性 Arrangement，
`--arrangement` 仅接受 0 或省略。FL 路径不用于 ALS；素材和 BMS 参数只在 ALS 渲染模式生效。

已实现的读取范围：

- Live 11 的 `ClipTimeable`、Live 12 的 `Sample` 及直接 Arrangement 容器。
- 轨道 ID、名称、分组和静态启用状态；MIDI 片段起讫、LoopStart/LoopEnd/StartRelative/LoopOn。
- 音高、力度、释放力度、时值、音符启用状态、概率，以及原始音符属性。
- 循环和片段裁剪展开；循环的首次源起点使用 `LoopStart + StartRelative`，后续回到 `LoopStart`。
  关闭循环时使用 `LoopStart`。持续音单独保存原始范围与裁剪后的可见范围。
- Session 片段单独列入 JSON，不虚构触发顺序；FreezeSequencer 和 Take Lane 不重复加入 Arrangement。
- 音频片段保留边界、SampleRef 与 WarpMarker 清单，不做音频转 MIDI 或渲染。
- 初始速度及 Arrangement 拍号事件写入 SMF Type 1 MIDI；轨道分开，保留原始 MIDI 音高编号和 0–127 力度。

时间与保真边界：

- JSON 的拍位置使用精确有理数字串，例如 `1/8`，原始十进位属性也保留。
- MIDI PPQ 是导出时选择的解析度，不宣称它是 ALS 的原生 PPQ。若无法在 MIDI 上限内精确表示，
  使用 PPQ 960 并警告，在 `midi_mapping.json` 记录最大误差与最短时值修正，JSON 不受损。
- 零拍之前的音符在 MIDI 中整体平移以保留；原始 JSON 位置不变，位移量写入 `beat_offset`。
- 静态停用、零力度、概率为零及零时值音符仍保留在 JSON，但不生成 MIDI 发声音符。
  对 0–1 之间的概率和力度变化，MIDI 输出潜在音符及基础力度，并警告未模拟随机播放。
- 速度自动化保留在 JSON，**当前 MIDI 只使用初始速度**，有变化时明确警告；拍号变化已支持。
- Groove、MPE、clip/track 自动化、Solo 路由和 MIDI 设备处理不模拟。裁剪持续音采用可见区间，
  在片段/循环边界的重新触发行为可能与 Live 不同，相关情况会警告。
- 不支持的循环范围不猜测展开，原始音符仍在 `clips[].notes` 中。未知容器的片段另存 XML 并警告。

本阶段已用合成 Live 11/12 夹具测试，并离线验证一个公开的 Live 11.1.5 工程：
4 个 MIDI 轨道，5506 条导出 MIDI 音符，17 个拍号事件。没有 Live 内的播放对照，
因此不承诺全部版本与所有播放语义兼容。格式调查及来源见 [docs/ableton-feasibility.md](ableton-feasibility.md)。

可选外部工程回归，不在代码中固定样本文件名或统计值：

```powershell
$env:DAW2BMS_TEST_ALS = "D:\Projects\song.als"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_als.py -v
```

## 切音流程（FLP）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[audio,test]"

# 自动探测尾音并重试，仅重渲染未通过校验的键音。
.\.venv\Scripts\python.exe -m daw2bms cut .\song.flp --out .\output\MyKeys --fl-exe "C:\Program Files (x86)\Image-Line\FL Studio 2026\FL64.exe"
```

`cut` 不使用统一固定尾音长度：初次使用短探测窗口，分析实际尾音包络的衰减速度和阈值差，
为未通过检查的键音重新计算窗口；无法预测衰减的音使用有上限的相对增长后重测。
已通过的键音不重新渲染。最后按实际波形结束位置裁掉尾部静音，保留起音延迟。
`--initial-tail` 只是初次探测范围，`--max-tail` / `--max-attempts` 是失败上限；
到达上限会明确报错并保留 MIDI 和中间结果，不截断声音冒充成功。
`result.json` 记录每轮结果，最终完整键音在 `keysounds/`。
可以用 `--resume <manifest.json>` 复用已经完成的、关闭循环的采样工程渲染。

也可以逐步执行，手动选择采样覆盖范围：

```powershell
.\.venv\Scripts\python.exe -m daw2bms prepare .\song.flp --out .\output\ManualKeys --fl-exe "C:\Program Files (x86)\Image-Line\FL Studio 2026\FL64.exe"

.\.venv\Scripts\python.exe -m daw2bms render .\output\ManualKeys\manifest.json --fl-exe "C:\Program Files (x86)\Image-Line\FL Studio 2026\FL64.exe"

.\.venv\Scripts\python.exe -m daw2bms slice .\output\ManualKeys\manifest.json
```

三个命令均须成功后再进行下一步。`prepare` 和 `slice` 拒绝覆盖已有目录；重新准备时换一个新目录。
FL 导出需要完整 Song、insert/master effects 开启、Trim PDC silence 开启、关闭 normalization。
命令行沿用 FL 的导出设置；未通过 GUI 自动更改它们。FL 的 WAV 位深会记录到渲染报告中，
切分输出默认 PCM 24-bit（不会让 16-bit 源文件获得更多精度），可用 `--subtype PCM_16` 改为 16-bit。

| 文件 | 用途 |
| --- | --- |
| `manifest.json` | 原曲事件 ↔ 独立键音 ↔ 采样位置的对应关系、资源检查和缺失通道 |
| `render_bank.flp` | 自动生成的采样工程副本；原插件/效果状态保留，可用音符依次排开 |
| `render_bank.wav` | FL 渲染出的键音序列，开头静音不可裁掉 |
| `song.mid` | 本次选择的全部通道音符，保持原曲 Playlist 位置 |
| `fallback.mid` / `fallback_notes.json` | 缺失音源通道的 MIDI 和未损失 FL 参数的原始记录；无缺失时不生成 |
| `keysounds/*.wav` | 校验通过的独立键音 |
| `keysounds/keysounds.json` | WAV 哈希、采样率、切分位置、响度峰值、尾音/间隔检查结果 |
| `keysounds/timeline.json` | 音频键音映射和 MIDI-only 音符，供后续 BMS 模块使用 |

默认按完整逐音记录（位置除外）去重，因此不同力度、声像、时值不会混用键音。
`--no-dedupe` 为每次放置独立渲染；使用随机相位/round-robin 音源时可选此模式。
`--channels 0,2,3` 仅采样指定 Channel Rack ID，`--arrangement 0` 选择编曲。

### 缺失资源降级

所有插件统一遵循“不可用则保留 MIDI 并警告”的规则，不限于 FLEX。
准备阶段检查采样文件、FLEX 软件包、任意原生音源/效果器 DLL，以及 VST2/VST3 文件或插件包。
混音器插件从第一个槽位开始检查；音源和效果器使用同一套可用性判定。
例如本例输出：

```text
WARNING: Channel 4 (FM Serpent Bass 01): unavailable/unverified Black Octopus Atlantis.flexpack; MIDI only, audio skipped.
```

缺失通道不渲染，音符保存在 `fallback.mid` 和 `fallback_notes.json`。
为了避免 FL 在加载时阻塞，**仅在采样副本内**将缺失/未参与采样的通道改为空的禁用 Sampler，
不会替换成其他可发声的音色。全部通道都缺失时仅生成 MIDI/JSON，`render` 和 `slice` 会警告并跳过。
效果器缺失时，因为当前尚未准确解析混音路由，保守地将本次选择的全部音符保留为 MIDI，
不启动音频渲染；警告明确列出插件、插入轨序号、槽位和降级范围。

可通过重复传入 `--resource-dir "D:\My FLEX Packs"` 指定额外素材目录，
或用 `--midi-only 4,5` 显式将无法渲染的通道降级。
FLEX 包名读取目前针对样本验证过的 v1 状态。无法解析的 Wrapper、FLEX 或 Patcher 嵌套插件状态
会记录在 `resources[].blockers` 并警告、保留 MIDI，不把未知当成可用，也不宣称已证实插件缺失。
第三方音源内部采样库和激活状态仍不能仅凭插件文件存在来验证，记录在 `resources[].unverified`。
FL 超时或渲染失败时报告错误，保留 `song.mid`，不会点击弹窗或把无声 WAV 当成成功。

### 切分校验

- 按绝对 tick 计算采样点，避免逐段舍入累积漂移；保留起音之前的静音/音源延迟。
- 检查每段有声、尾部安静、键音之间的保护间隔安静、PCM 不削波、没有 NaN/Infinity。
- 默认静音阈值 -60 dBFS，尾部额外保留 20 ms，末尾静音区内淡出 3 ms；不逐音归一化。
- 发生尾音/串音问题时写出 `slice_diagnostics.json` 并拒绝输出整组键音，
  推荐使用 `cut` 自动调整并重试；手动模式也可指定 `prepare --tail`。渲染 WAV 可以用 `slice --wav <文件>` 显式指定。
- 当前要求固定 BPM、4/4、普通 Pattern 片段；自动化、滑音、循环、跨裁剪边界的持续音会被拒绝。
- 保留了原效果器，但独立音符经过共享压缩、侧链、连奏等处理后，不能保证相加等同于原混音。

MIDI 为标准 SMF Type 1，按 FL 通道分轨，保留 PPQ 和原曲位置。
FL 零长度步进音符使用 1/16 音符 MIDI gate；力度按 0–128 映射至 MIDI 0–127。
不能在标准 MIDI 中表达的 FL 参数以 JSON 为准；超出 MIDI 音高范围等情况有警告。

## BMS 导出与播放器测试

```powershell
python -m daw2bms bms .\output\MyKeys\keysounds --out .\output\MyBMS --title Song
```

只接受 `status=complete` 的键音包，检查音频 SHA-256、WAV 格式和逐音引用，再生成自包含文件夹。
使用 `.bme` 扩展名明确表示 BMS 家族的 7 键谱面，使用常规 `#WAV01..ZZ` 和通道 `11–15,18,19`。
输入须为 PCM 16/24-bit 单声道或立体声 WAV，导出保持音频字节不变。

- 将整个输出文件夹加入 beatoraja/LR2 等播放器的曲库路径并刷新，打开 `test.bme`；保留 `audio/` 子目录。
- 建议先用 AUTO PLAY 检查声音和节奏，再手动测试。此处只验证了格式解析，未通过 GUI 操作播放器。
- 默认在原曲前加入 1 小节准备时间；`--lead-in-bars 0` 可关闭。映射保持整数 tick，不量化。
- 当前为固定 BPM、4/4、7 键短音符，无转盘和长条。自动分配键位用于验证导出，`PLAYLEVEL 1` 是占位值。
- 同时音符超过 7 个时，额外声音转入通道 `01` 自动播放，重复 BGM 行保留所有同时发声。
- `--play-channels 0,2,3` 可只将指定 FL 通道安排为可玩音符，其他通道进入 BGM。
- 同一个键音在尾音尚未结束时再次触发，会使用独立 WAV 文件和编号，避免重触发截断上一段尾音。
- 缺失插件的音符不会被伪造为静音键音；保留 `fallback.mid`、`missing_notes.json` 并警告，标题带 `[MISSING AUDIO]`。
- 默认 UTF-8，当前示例的 BME 文本和 WAV 路径全为 ASCII。旧播放器可选 `--encoding cp932`；无法编码的文字会报错。

| 文件 | 内容 |
| --- | --- |
| `test.bme` + `audio/*.wav` | 可直接交给播放器的谱面和独立键音 |
| `mapping.json` | 每个 BMS 事件对应的原始 FL 通道、Pattern、片段、音符及 tick |
| `export_report.json` | 音符/BGM 数量、准备时间、完整性和逐事件回读校验结果 |
| `fallback.mid` + `missing_notes.json` | 缺失音源的音符，保持原曲位置，不包含准备小节 |

本地研究样本的导出验证结果：130 BPM，680 个可玩音符 + 92 个 BGM 事件，
覆盖 772 次原曲发声；128 个键音使用 130 个 WAV 定义（包含重叠发声所需的副本）。
缺失 FLEX 的 100 条音符仍为 MIDI-only。

除内部精确有理数回读，还使用 Bemuse 的独立 `bms@51.0.0` 解析器验证全部事件、WAV 引用和秒数，
结果保存在 `external_validation.json`。开发验证可这样重现（不是运行时依赖）：

```powershell
npm install --prefix .scratch\bms-validation --ignore-scripts --no-audit --no-fund bms@51.0.0
node tests\validate_bms.cjs output\MyBMS .scratch\bms-validation\node_modules\bms
```

格式参考：[BMS command memo](https://hitkey.bms.ms/cmds.htm)；
独立解析器：[bemusic/bms-js](https://github.com/bemusic/bms-js)。

## 仅提取结构

在项目目录执行：

```powershell
python -m daw2bms extract .\song.flp
```

指定输出目录：

```powershell
python -m daw2bms extract .\song.flp --out .\output\Song
```

再次生成同一组输出时加 `--force`。默认拒绝覆盖已有输出；输入 FLP 始终只读。
也可以用 `python -m pip install -e .` 安装命令行入口，然后运行 `daw2bms extract ...`。

## 输出文件

| 文件 | 内容 |
| --- | --- |
| `project.json` | 完整结构：项目参数、通道、Pattern 原始音符、所有 Arrangement、轨道、片段、展开音符、诊断 |
| `pattern_notes.csv` | 每个 Pattern 的原始音符；不会因 Playlist 重复放置而重复 |
| `playlist.csv` | 每个片段的位置、长度、轨道、Pattern/通道引用、源裁剪范围、展开状态 |
| `timeline_notes.csv` | 按 Playlist 位置展开的音符；保留原 Pattern、片段和音符编号 |
| `summary.txt` | 可直接阅读的中文统计和片段清单 |

JSON 是主数据格式；CSV 是便于查看的字段子集。CSV 使用 UTF-8 BOM，适合在 Windows Excel 中打开。
JSON 使用标准 UTF-8，禁止 NaN/Infinity；未解码或未设置的值是 `null`。

## 时间和音符约定

- `*_ticks` 保留 FLP 整数时间；`*_beats = ticks / PPQ`，beat 表示四分音符，从 0 开始。
- Playlist `track_id` 从 1 开始；Pattern、Channel、Arrangement ID 保留文件编号，不重新编号。
- `key_name_fl` 遵循 FL 命名：key 60 = **C5**。不要与科学音高命名 C4 混用。
- `velocity_raw`、`pan_raw` 等保留 FL 数值，未转换成 MIDI 的 0–127 范围。
- `length_ticks = 0` 是步进触发音符的一种表示，不丢弃，不猜测声音时长。
- Pattern 偏移中的 `-1` 保存为 `null`（未设置）；Pattern 和音频片段的偏移存储语义不同。

当前展开计算：

```text
absolute_onset_ticks = clip.position_ticks + note.position_ticks - source_start_ticks
```

源起点未设置时取 0。每次 Playlist 放置独立展开，保留片段可见范围内的音符和跨边界长音。
`absolute_onset_ticks`、`length_ticks` 始终保留原始音符的映射结果；
`visible_start_ticks`、`visible_end_ticks` 单独表示几何交集。
跨左边界的音符可能有早于片段起点的 onset，`onset_inside_clip=false`，不表示应在该位置重新触发。
FL 的截断音符设置保存在 `project.play_truncated_notes`，当前不模拟它的播放结果。

## 支持范围

读取目标是 FL 25/26 的现代布局，明确验证过的真实样本只有下表所列文件。
现代头部、事件边界、音符记录长度、Playlist 记录长度、通道计数及引用均有检查；
不支持或损坏的二进制布局会报错，不尝试跳过字节重新同步。

| 验证对象 | 结果 |
| --- | --- |
| 本地研究样本，保存版本 `25.2.4.5242` | 7 个通道、6 个 Pattern、355 个原始音符、1 个 Arrangement、17 个片段、872 条展开记录 |
| 本机 FL Studio 安装版本 | `26.1.7.5654`；这不等于样本由该版本保存 |
| FL 26 布局单元测试 | 使用合成二进制夹具；尚未验证真实 FL 26 重新保存的工程 |
| FL 26 命令行实际渲染/切音 | 本地研究样本：128 个 WAV 对应 772 次触发；缺失 FLEX 的 100 条音符转存 MIDI |

本例自适应验证经过 3 轮，分别新增通过 61、66、1 个键音；最终 WAV 实际时长约 0.121–3.801 秒。
没有统一固定尾音长度。原始 FLP 哈希未变化。
结果目录包含：`keysounds/`、`fallback.mid`、`song.mid`、`result.json`。

示例参数：PPQ 96、文件保存 BPM 130、拍号 4/4、6 条有片段的 Playlist 轨道。
Playlist 终点为 7680 ticks / 80 个四分音符，即按 4/4 计 20 小节。
样本不随源码分发，`.gitignore` 排除 FLP 和生成输出。

### 当前边界

导出的是 **存储结构和单次 Pattern 放置的几何时间轴**，不是 FL 播放引擎：

- 自动化、Tempo 曲线、摆动、通道循环、移调、Layer 路由、插件生成的音符和音频播放不计算。
- 保留轨道和通道 enabled 状态，但不据此删除音符；片段 mute 位未验证，导出为 `null`。
- 不根据音符末尾猜测 Pattern 周期，不自动补循环。明确标记 looped 的 Pattern、非 1 倍 scale、
  与片段长度不一致的裁剪窗口保留原始结构并发出 `CLIP_NOT_EXPANDED`，不虚构展开结果。
- 普通重复放置支持；拉长后的隐式循环及通道级循环尚不支持。
- `stored_tempo_bpm` 是文件保存的值，不能当作整首曲子的恒定 BPM，因此不导出秒数。
- 音频/自动化片段保留通道引用和原始偏移，不由波形推断音符。
- 未解释的事件记录在诊断计数中；这不是完整 FLP 反序列化器。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖 3 字节特殊事件、80 字节 Playlist 边界、同一 Pattern 两段元数据合并、
重复放置、整数裁剪偏移、跨边界音符、零时值步进音符、多个 Arrangement、
静音状态保留、损坏数据拒绝、CLI 导出和输入文件未改动。
测试使用代码生成的合成夹具，不依赖仓库目录中的任何示例 FLP。
可通过环境变量显式指定任意受支持的本地工程，额外验证事件数量、音符原始字节和只读行为：

```powershell
$env:DAW2BMS_TEST_FLP = "D:\YourProjects\song.flp"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

未设置该变量时跳过外部工程测试；不预设文件名、样本哈希、音符数或片段位置。

新增测试覆盖缺失 FLEX/采样降级、采样副本中插件中和、MIDI 独立读取、去重、尾音隔离、
浮点/PCM WAV、样本精度、渲染超时和输入未改动。`test` extra 中的 mido 用于独立验证 MIDI。

代码入口：`daw2bms/flp.py`（解析与时间轴）、`daw2bms/keysounds.py`（采样工程）、
`daw2bms/resources.py`（资源预检）、`daw2bms/midi.py`（MIDI）、
`daw2bms/audio.py`（渲染/切音）、`daw2bms/adaptive.py`（尾音检测与重试）、
`daw2bms/bms.py`（测试谱导出）、`daw2bms/als.py`（ALS 读取）、`daw2bms/als_export.py`（ALS MIDI/JSON）、
`daw2bms/pipeline.py`（端到端转换）、`daw2bms/__main__.py`（CLI）。
格式调查记录见 [docs/flp-format.md](flp-format.md)。

下一步：用真实 FL 26 保存的最小工程交叉验证裁剪、静音、循环和变速；
之后扩展可玩性编排、长条及变速谱面支持。
