# DAW2BMS

将 FL Studio / Ableton Live 工程转换为带独立键音的 BMS 测试谱，并接入 BMSE 继续编辑。

读取工程中的音符与编曲时间轴，按音轨选择「按键音符 / BGM / 不导出」，再调用本机 DAW 渲染、自动切音，将键音放回原曲时间位置。输入工程只读，采样和渲染使用新建副本；缺失插件或素材时保留对应 MIDI 并警告。

当前生成的是 **7 键自动排键测试谱**，适合验证声音与时间轴。最终排键、长音符和难度设计可在 BMSE 中继续完成。

## 支持情况

| 功能 | FL Studio | Ableton Live |
| --- | --- | --- |
| 工程格式 | `.flp`，主要面向 FL Studio 2026 | `.als`，Live 11 / 12 Arrangement |
| 音符与时间轴读取 | Pattern + Playlist | Arrangement MIDI Clip |
| 轨道用途选择 | 按 Playlist 音轨 | 按 Arrangement 音轨 |
| MIDI 导出 | 支持 | 支持，无需安装 Live |
| 独立键音渲染 | FL 命令行导出 | Windows 原生导出窗口自动化，需手动启用 |
| BMS 导出 | 有可用键音时生成 | 启用渲染且有可用键音时生成 |
| 缺失设备 | 保留 MIDI、警告 | 保留 MIDI、警告 |

音频转换当前面向 Windows、固定速度和 4/4 工程。并非所有设备、路由或播放语义都能还原，详见[当前限制](#当前限制)。

## 安装

需要 **Python 3.10+**。在项目根目录执行，已有虚拟环境时可跳过创建：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[audio,ableton]"
```

按需要选择依赖：

| 安装选项 | 用途 |
| --- | --- |
| `pip install -e .` | 结构读取与 MIDI 导出 |
| `pip install -e ".[audio]"` | FL 渲染后的音频检查、切音与 BMS 导出 |
| `pip install -e ".[audio,ableton]"` | BMSE 集成或 CLI，含 Ableton 桌面导出依赖 |
| `pip install -e ".[gui,ableton]"` | 独立 PyQt6 GUI，含两种 DAW 的音频流程 |

表中的 `pip` 应使用同一个虚拟环境。依赖安装不会安装 FL Studio、Ableton Live、音源或素材库；音频转换需要这些资源已在本机可用。

## 快速开始

以下 PowerShell 示例从 DAW2BMS 项目根目录运行。工程路径均为占位示例，请替换为自己的文件。

### FL Studio：一条命令生成谱面

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.flp"
```

流程为读取工程 → 检查资源 → 创建采样副本 → FL 渲染 → 自适应切音 → 导出 BMS。自动检测 FL 安装位置，也可指定：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.flp" --fl-exe "D:\Apps\FL Studio 2026\FL64.exe"
```

CLI 默认在当前目录的 `output/<工程名>-bms/` 输出，重名时递增后缀。指定 `--out` 时应使用尚不存在的目录，避免覆盖旧结果。

### 选择哪些轨道变成按键

先读取实际轨道 ID：

```powershell
.\.venv\Scripts\python.exe -m daw2bms tracks "D:\Projects\song.flp"
```

假设列表中有轨道 `1`、`3`、`8`，只把 1、3 做成按键，排除 8，其他轨道自动播放：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.flp" --play-tracks 1,3 --exclude-tracks 8
```

| 用途 | 行为 |
| --- | --- |
| 按键音符 | 渲染键音并生成可按音符 |
| BGM | 渲染键音，放到 BMS 自动播放通道 |
| 不导出 | 从本次渲染和 MIDI 选择中排除 |

FL 的选择依据是 **Playlist 音轨**，并非 Channel Rack 音源通道，因此同一音源放在不同轨道上可以有不同用途。ALS 使用 Arrangement 音轨 ID；不要将界面显示顺序当成 ID。

**CLI 不传 `--play-tracks` 时默认全部入选音符作为按键；GUI 默认将可用轨道设为 BGM。** `--play-tracks none` 可生成纯 BGM 测试谱。BGM 当前也是独立键音按时间自动触发，并不是原曲整轨混音。

### Ableton：读取 MIDI 或启用渲染

默认仅提取 Arrangement 与 MIDI，不启动 Live：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.als"
```

已安装 Live 时，显式启用音频转换：

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.als" --ableton-render
```

可用 `--ableton-exe "D:\Apps\Live\Program\Ableton Live 12 Suite.exe"` 指定安装位置。

音频由 Live **原生离线导出**，PyAutoGUI 操作导出窗口，pywinauto 读取控件。该流程需要可交互的 Windows 桌面：先保存当前 Live Set，运行期间保持 Live 在前景并避免操作其窗口。未知弹窗、焦点变化或超时会停止自动操作；鼠标移到主屏幕角落可触发 PyAutoGUI 紧急停止。

支持已验证的原生设备及 VST2/VST3 静态设备链。外部插件须先在 Live 中启用对应目录并完成扫描；转换器不会用同名插件替换缺失插件。

Max for Live 还需要在 Live 控制介面中启用 **AbletonMCP Remote Script**，用于只读核对设备状态；不需要运行 Codex 或 MCP 客户端。缺少脚本、设备依赖或无法验证状态时保留 MIDI。安装记录及边界见 [Ableton 说明](docs/ableton-feasibility.md)和[技术参考](docs/workflow-reference.md#max-for-live)。Audio Unit 暂未实现。

## 在 BMSE 中使用

Wails 3 重写版 BMSE 已接入同一个转换引擎。完整发布包附带 Python 运行时与转换依赖，无需另外安装 Python、PyQt6 或配置引擎路径。FL Studio、Ableton Live 和音源仍须在本机安装。

1. 解压完整的 `BMSE3-Windows-x64.zip`，保留 `BMSE3.exe` 旁的 `daw-engine/` 文件夹。
2. 源码构建可在 BMSE 目录执行：

   ```powershell
   cd C:\DAW2BMS\BMSE
   .\build.ps1
   ```

   构建需要 Go、Node.js 和 Python；脚本准备构建依赖并生成 `bin/BMSE3-Windows-x64.zip`。运行发布包不需要这些开发工具。

3. 启动 `bin/BMSE3.exe`，选择 **文件 → 导入 DAW 工程…**，或拖入 `.flp` / `.als`。
4. 读取音轨，设置按键 / BGM / 不导出；ALS 要生成音频时勾选 Ableton 渲染。
5. 转换结束后点击「在 BMSE 开启谱面」。处理当前谱面的未保存提示后，结果作为**独立新谱面**打开，继续编辑和测试。

BMSE 默认在源工程旁的 `output/` 新建带唯一后缀的输出目录，也可选择其他父目录。MIDI-only 或取消结果不会替换当前谱面；导入窗口可查看日志、警告和输出文件。

导入窗口的「转换引擎设置」默认使用内置引擎；开发时可改为外部 Python。旧版本保存的外部环境设置继续保留，可手动切回内置引擎。只有外部 Python 模式需要保留源代码目录和相应环境。

BMSE 源码位于本仓库的 `BMSE/`，构建、设置与编辑功能见 [BMSE README](BMSE/README.md)。首次构建在该目录执行 `.\build.ps1`，生成 `bin/BMSE3.exe`。

## 独立桌面界面

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui,ableton]"
.\.venv\Scripts\python.exe -m daw2bms gui
```

也可追加工程路径预填文件框：

```powershell
.\.venv\Scripts\python.exe -m daw2bms gui "D:\Projects\song.flp"
```

左侧选择工程和参数，右侧设置轨道用途、查看进度与日志。可打开输出目录、MIDI 和谱面报告；「停止后续步骤」等待当前操作安全结束并保留已有文件，不强制终止 DAW。

## 输出与播放器测试

一次有键音的转换通常包含以下文件；具体以 `conversion.json` 中记录的路径和状态为准：

```text
<输出目录>/
├── conversion.json       转换状态、警告、轨道用途与结果路径
├── project.json          提取的工程结构与时间轴
├── song.mid              本次入选音符的 MIDI
├── fallback.mid          无法渲染的音符（按结果生成）
├── fallback_notes.json   回退音符及原因（按结果生成）
├── work/                 采样副本、渲染记录、切音与重试文件
└── chart/
    ├── test.bme          7 键 BMS 测试谱
    ├── audio/            独立 WAV 键音
    ├── mapping.json      键音与源工程音符、时间位置的映射
    ├── export_report.json
    └── README.txt
```

用支持 BME 的播放器或 BMSE 打开 `chart/test.bme`。移动或分享时保留整个 `chart/` 目录，WAV 使用相对路径引用。默认增加一个准备小节，可通过 `--lead-in-bars` 调整。

没有可用键音时只保存 MIDI 和报告，不生成空白或无声的假谱面。部分设备缺失时，可用部分仍能生成谱面，但应检查警告和音频完整性标记。

## 语言

命令行、独立 GUI 与 BMSE 导入窗口支持 `zh-TW` / `en` / `ja` / `ko`。未手动设置时跟随操作系统 **UI 语言**；中文对应繁体中文，不支持的语言回退英文。

```powershell
.\.venv\Scripts\python.exe -m daw2bms convert "D:\Projects\song.flp" --lang en
```

CLI 优先顺序为 `--lang` → `DAW2BMS_LANG` → 系统语言。GUI 手动选择会记住，可恢复「跟随系统」。BMSE 导入窗口的语言设置与原编辑器 INI 语言独立。路径、插件名称、JSON 字段和第三方原始错误保持原样。

## 当前限制

- **排键是确定性的测试编排。** 同一输入与参数产生相同排键，不是每次随机；优先使用较久未用的空闲键，同刻超过 7 个按键的声音转入 BGM。暂不自动设计转盘、长音符、手法或难度。
- **音频还原不等于整曲混音还原。** 隔离音符可能改变连奏、压缩、侧链、随机音源或依赖播放上下文的设备行为。
- **音频流程主要支持固定速度、4/4。** 变速、复杂路由、自动化、Groove、MPE 及无法确认的裁剪/循环语义存在限制；遇到不支持内容会警告、回退 MIDI 或拒绝继续，不推测播放结果。
- **音频片段不会从波形推断音符。** ALS 以 Arrangement 为准，不将 Session、冻结或 Take 内容假定为实际播放音符。
- **缺失设备保留 MIDI。** 包括 FLEX 音色包、VST、Max 设备及可检测到的素材缺失；无法读取或损坏的工程不保证能导出 MIDI。插件内部未报告的素材替换和 Max 隐藏依赖无法完全检测。
- **尾音自适应检测。** 依据音量阈值扩展并重试，受 `--max-tail` / `--max-attempts` 上限约束，不固定延长 6 秒，也不保证覆盖无限反馈或任意长混响。
- **Ableton 桌面自动化依赖环境。** 已验证的 Live 版本、界面和设备不能代表所有版本；无法确认导出状态时停止，不自动跳过未知弹窗。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| 只有 MIDI，没有 BMS | 查看警告和 `conversion.json`；ALS 默认不渲染，FL/Live 未安装或全部设备不可用也会回退 |
| 全部声音变成按键 | CLI 用 `--play-tracks` 指定轨道；GUI 中逐轨改为 BGM 或不导出 |
| BMSE 找不到转换引擎 | 检查 Python 路径、引擎根目录及该环境的依赖，重新运行 `configure-daw.ps1` 或修改导入设置 |
| 已安装插件仍报告缺失 | 检查 Live 扫描目录、插件格式/ID、授权与素材库；M4L 还需检查 Remote Script 与 `.amxd` 依赖 |
| 尾音重试达到上限 | 检查设备反馈与持续噪音，再按需要调整最大尾音、检测阈值和重试次数 |
| 输出目录已存在 | 换一个新的 `--out`，或省略它以自动生成新目录 |
| 播放器找不到键音 | 保留 `test.bme` 与同级 `audio/` 的相对位置 |

## 开发与参考

安装测试依赖并运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui,ableton,test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

常规测试使用生成的合成工程，不依赖个人示例文件。外部工程验证为可选项；示例 FLP/ALS、虚拟环境和生成输出均由 `.gitignore` 排除。不要将商业音源、工程素材或渲染结果添加到源码仓库。

| 入口 | 内容 |
| --- | --- |
| [工作流与技术参考](docs/workflow-reference.md) | 分阶段命令、完整参数示例、时间约定及验证记录 |
| [FLP 格式调查](docs/flp-format.md) | FLP 事件及解析边界 |
| [Ableton 可行性与实现记录](docs/ableton-feasibility.md) | ALS、原生导出、插件与 MCP 验证 |
| [命令行](daw2bms/__main__.py) / [转换管线](daw2bms/pipeline.py) | CLI 与一键转换 |
| [BMSE 桥接](daw2bms/bridge.py) | stdin JSON 请求、stdout JSON-lines 事件、取消和源文件哈希校验 |
| [独立 GUI](daw2bms/gui.py) | PyQt6 界面 |

使用 `python -m daw2bms --help` 或 `python -m daw2bms convert --help` 查看当前版本的全部选项。
