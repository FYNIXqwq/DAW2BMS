# DAW2BMS

将 DAW 工程的音乐结构提取为可用于后续 BMS 制作的中间数据。
当前版本支持 **FLP 结构提取、独立键音工程生成、FL 命令行渲染、WAV 切音和 BMS 测试谱导出**。
遇到缺失资源的通道会保留 MIDI 并在命令行警告，其他可用通道继续处理。
输入 FLP 始终只读，改动仅发生在新建的采样工程副本中；不使用 computer use / GUI 自动化。

## 运行

需要 Python 3.10 或更新版本。结构提取、MIDI 导出和工程准备只用 Python 标准库，无须 PyFLP。
音频渲染需要本机 FL Studio 及可用的音源；WAV 校验/切分使用可选 `audio` 依赖。

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

- 支持繁體中文、English、日本語、한국어的单窗口，中性深灰界面，少量蓝色强调。左侧选择或拖入 FLP、选择输出父目录；右侧查看进度、日志和警告。
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

命令依次读取 FLP、检查资源、生成采样副本、自适应渲染/切音并导出 BMS。
不依赖特定示例文件，不操作 GUI，也不会修改原工程。
默认输出到当前目录的 `output/<工程名>-bms/`；目录已存在时自动使用 `-2`、`-3` 等后缀。
使用 `--out <新目录>` 可以指定输出位置，显式指定的已有目录不会被覆盖。

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

## 切音流程

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
`daw2bms/bms.py`（测试谱导出）、`daw2bms/pipeline.py`（端到端转换）、`daw2bms/__main__.py`（CLI）。
格式调查记录见 [docs/flp-format.md](docs/flp-format.md)。

下一步：用真实 FL 26 保存的最小工程交叉验证裁剪、静音、循环和变速；
之后扩展可玩性编排、长条及变速谱面支持。
