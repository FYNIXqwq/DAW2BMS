# BMSE — Web + Wails 3 重写版

这是原 BMSE 的 **独立重写工程**，不是原 VB.NET 二进制的包装。按用户要求保留原版菜单、工具栏、左侧信息/素材面板、向上推进的谱面、轨道配色与主要快捷键。本目录从原 Wails 工程复制到 DAW2BMS 仓库，保留源码、构建资源、许可和合成测试素材；原 VB.NET 工程未包含在本目录中。

技术栈：Go 1.26、Wails **v3.0.0**、React 18、TypeScript、Vite。当前构建与验证目标是 **Windows amd64**。日常编辑及主要旧版配置、BGA、素材整理功能已迁移；精确兼容边界见下文。

最新原版对照、数据完整性修复与测试证据见 [审查报告](AUDIT_2026-10-28.md)。本轮覆盖读写、移动/变拍子、素材引用、撤销/恢复、配置竞争和无界面交互回归。

从 DAW 开始制作谱面可直接阅读[DAW 工程导入](#daw-工程导入)：读取 FLP/ALS → 选择按键、BGM 或排除的轨道 → 自动渲染切音 → 作为新谱面打开并继续编辑。
转换引擎的安装、命令行及支持边界见上级目录的 [DAW2BMS 使用说明](../README.md)。

## 运行

完整发布包为 `bin/BMSE3-Windows-x64.zip`。解压后运行 `BMSE3.exe`，保留旁边的 `daw-engine/`：其中包含 Python 运行时与 DAW 转换依赖，使用者无需安装 Python。Windows 仍需要 WebView2 Runtime。源码仓库不包含构建产物，首次使用可按下文构建。

源码中的 `samples/roundtrip.bms` 是自动化测试使用的文本谱面。若要手动试听，先在本目录运行 `node samples/create-audio.mjs` 生成 kick/snare/hat/tone.wav，再用“文件 → 打开”载入该谱面。生成的音频不包含外部音乐，也不提交 Git；双击 WAV 条目可以试听。

## 构建

已验证环境：Go 1.26.7、Node.js 24.15.0、npm 12.0.2。

```powershell
cd C:\DAW2BMS\BMSE
# 可选但推荐：安装与运行时相同版本的 Wails CLI
go install github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0
.\build.ps1
```

`build.ps1` 执行前端依赖安装、类型检查与构建、Go 测试、Windows 资源生成（存在 wails3 时），然后生成 `bin/BMSE3.exe`。接着用 PyInstaller 打包 Python 引擎，验证音频依赖、翻译资源及 Ableton 辅助进程入口，生成完整 ZIP。构建机还需要 Python 3.10+；默认使用仓库根目录 `.venv`，可传 `-Python` 指定其他构建环境。

已有前后端构建依赖时可用 `-SkipInstall`。仅开发编辑器可用 `-SkipEngine`；单独重建转换引擎用 `.\build-engine.ps1`。开发依赖不随应用发布，发布包不包含示例工程、转换输出或用户配置。

开发模式：`wails3 dev`。运行时和前端 runtime 均固定为 3.0.0；不要用 Wails 2 CLI。

## 测试

```powershell
.\test.ps1             # Go + TypeScript 模型测试
.\test.ps1 -Browser    # 再构建并运行无界面浏览器测试与真实 Wails 服务桥接测试
```

浏览器测试使用本机 Chrome，默认路径在 `frontend/playwright.config.ts`；其他机器可调整此路径。测试只监听 `127.0.0.1:9246` 和 `127.0.0.1:9247`，需要端口空闲。脚本将 Wails 设置/恢复文件隔离到 `bin/test-config`，结束时停止自己启动的服务。整个流程不需要 Computer Use。

也可仅启动不具备桌面文件权限的 Web 预览：

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
go run ./cmd/preview
# http://127.0.0.1:9246/
```

Web 预览共用 Go 解析器，可通过浏览器选择文件、编辑和下载 BMS；外部播放器与原生文件路径操作在桌面版使用。Web 预览不是部署到公网的服务。

## DAW 工程导入

桌面版通过 **文件 → 导入 DAW 工程…**，或直接拖入一个 `.flp` / `.als`，接入 DAW2BMS 转换流程：

1. 选择工程并读取音轨。
2. FL Studio 按 Playlist 音轨、Ableton 按 Arrangement 音轨，设置按键音符、BGM 或不导出。默认 BGM；不支持的内容保持排除。
3. 按需调整尾音探测、重试上限、超时、谱面标题/作者、准备小节、音源路径及额外素材目录。
4. 开始转换，在窗口内查看阶段、日志、缺失设备警告和结果。停止请求等待当前操作安全结束，不强杀 DAW。
5. 点击“在 BMSE 开启谱面”，先处理当前谱面的未保存确认，再作为**独立新谱面**载入。生成的 WAV 相对路径保持有效，可继续排键、改长音符、调整难度和保存。

缺失音源/设备仍保留 MIDI。MIDI-only 或取消的结果不会替换当前谱面，可打开输出目录查看保留文件。
默认在源工程旁的 `output/` 中新建带唯一后缀的目录，不覆盖旧转换；也可以选择其他输出父目录。
转换中的原生关闭、Esc 和对话框关闭均受保护。重新打开导入窗口可查看当前进程内的上次结果或正在运行的任务。

导入窗口支持 zh-TW / en / ja / ko；Windows 默认读取操作系统 UI 语言，手动选择会记住。
原编辑器的旧版 INI 语言和主题继续独立工作。

### 内置转换引擎与开发设置

发布版默认调用同目录下 `daw-engine/DAW2BMS.exe`，包含 Python 和音频/桌面自动化依赖，不启动 PyQt6 GUI。移动整个发布目录后仍可使用，不依赖打包机器的路径。不要单独移动 BMSE3.exe。DAW 与音源不包含在发布包内。

导入窗口的「转换引擎设置」可以选择内置引擎或外部 Python。旧版保存的 Python 设置保持有效；需要使用发布包时选择内置引擎。内置文件缺失会明确提示恢复文件夹，不会静默换用系统 Python。

以下步骤仅用于开发或指定外部引擎，普通使用者无需执行：

```powershell
# 在 DAW2BMS 项目中（已有虚拟环境可省略创建步骤）
cd C:\DAW2BMS
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[audio,ableton]"

# 在此 Wails 工程中
cd C:\DAW2BMS\BMSE
.\configure-daw.ps1 -EngineRoot "C:\DAW2BMS"
# 若 Python 位于其他环境，可追加 -Python "D:\Tools\python.exe"
# 需要从源码构建时执行；已有可执行文件可跳过
.\build.ps1
```

上述目录是本机布局示例，请替换为实际位置。外部 Python 模式需要保留 DAW2BMS 目录及其 Python 环境。

配置脚本写入被忽略的 `bin/daw-import.json`。也可以在导入窗口的“转换引擎设置”中修改，
该设置存于 `%APPDATA%\BMSE-Wails\daw-import.json`，优先于 EXE 旁的配置。
未配置时优先使用 `DAW2BMS_PYTHON` / `DAW2BMS_ROOT` 的显式环境设置，其次选择内置引擎；源码开发还会检测同仓库引擎及 `.venv`。也可选择已经安装 `daw2bms` 的 Python，原始码目录留空。
源工程路径、引擎路径和示例文件均未硬编码进应用。

FL Studio 使用其命令行渲染。ALS 默认只导出 MIDI；勾选“使用 Ableton 渲染 ALS”后操作原生离线导出窗口，
需要保存当前 Live Set 并保持 Live 在前景。Max for Live 还需要启用 AbletonMCP Remote Script。
支持范围沿用引擎：固定速度/4拍原型、已验证的原生/VST2/VST3/Max 设备；Audio Unit 和不能验证的状态保留 MIDI。
BGM 当前沿用键音自动播放，并非完整编曲混音；生成的是自动排键测试谱，最终谱面制作仍在 BMSE 中完成。

### 集成验证

Go 侧验证进程协议、取消、并发/关闭保护、新输出目录、结果路径边界和相对素材载入；Python 侧验证真实分析、MIDI 回退和取消时保留文件。
浏览器测试走真实 Wails 服务，覆盖轨道角色传递、生成谱面打开、未保存确认、取消、MIDI-only，以及原编辑器回归。
可额外设置 `DAW2BMS_TEST_ENGINE` 与 `DAW2BMS_TEST_PYTHON` 后运行 `test.ps1 -Browser`，启用真实 Python ALS 读取/MIDI-only 集成用例；其他导入用例使用隔离的协议测试引擎，不启动 DAW。

## 迁移情况

下表是 **BMSE 编辑器已经实现的能力**。DAW 转换引擎目前自动生成七键普通音符测试谱，不能据此认为转盘、长音符、多键模式或变速也已支持从 DAW 自动转换。完整状态见[项目功能实现状态](../README.md#功能实现状态)。

| 原版区域 | 当前实现 |
| --- | --- |
| 主界面 | 菜单、工具栏、基本/扩展/显示标签、WAV/BMP/BGA/小节/扩展标签、直接输入、状态栏 |
| DAW 导入 | FLP/ALS 分析、按轨道选择按键/BGM/排除、调用 DAW2BMS 切音与导出、日志/取消、作为新谱面载入 |
| BMS 文件 | BMS/BME/BML/PMS；头部信息；16/36/62 进制；WAV/BMP/BGA；BPM/STOP/SCROLL/SPEED |
| 数据精度 | 读入保留原分子/分母；输出按轨道计算最小分割；过大分割报错，不静默舍入 |
| 谱面画布 | SP 5/7 键、2P/DP 10/14 键、PMS 9 键、OCT/FP、转盘左右位置、最多 128 BGM 列、缩放、网格、定位 |
| 编辑 | 写入、框选、Ctrl 增减选择、拖动/方向键移动、删除、普通/不可见/LN/地雷、精确属性编辑 |
| 长音符 | LN 通道端点配对、LNOBJ 显示；LN 通道缺失端点、LNOBJ、区间冲突检查；LNTYPE 2 导入归一化 |
| 撤销与重做 | 谱面、素材、头部、小节操作；最多 150 个快照，按文档大小降低历史数量以限制内存 |
| 剪贴板 | 读写 BMSE 3 Double 位置格式；读取旧 BMSE 格式与常用 iBMSC 剪贴板格式 |
| QuickSend | 原 SP/DP/PMS 键位；默认最早且最左对象；Shift 批量；空格发送至新 BGM 列 |
| 小节 | 倍率、插入、删除；同时平移扩展区中可识别的小节行 |
| 查找替换 | 按小节范围、轨道、编号/数值和属性筛选；选中/删除/替换 |
| 素材 | 文件选择、多文件导入、路径编辑、音频/图像/浏览器支持的视频预览、编号交换 |
| 转换 | 清除未用定义；按编号或文件名重排；同步音符、LNOBJ、BGA 引用；有条件分支时拒绝不安全的整理 |
| 检查/统计 | 重叠、未定义素材、LN 通道端点、BPM；1P/2P 属性统计与 BGM 数量 |
| 编码 | UTF-8、Shift-JIS、EUC-KR、UTF-16/32 大小端；BOM/UTF-8 自动检测；可手动重载 |
| 播放器 | 可配置可执行文件及播放/当前小节/停止参数；无 shell 字符串拼接；多配置管理与旧版 INI 导入；默认 uBMplay 参数 |
| 文本编辑 | 直接输入 BMS 行、完整 BMS 文本编辑与重新解析 |
| 文件安全 | 同目录临时文件、flush、替换；序列化不修改内存；失败保留旧文件；未保存提示、恢复备份、最近文件 |

### DAW 整合与打包状态

| 状态 | 功能 |
| --- | --- |
| 已实现 | FLP/ALS 导入、轨道用途选择、渲染与切音、测试谱打开、MIDI 回退、日志、取消和未保存保护 |
| 已实现 | Windows x64 发布包内置 Python 转换运行时；内置/外部引擎切换；导入窗口四语言及系统语言默认选择 |
| 有限支持 | Ableton 桌面导出、原生/VST2/VST3/Max 设备验证；仍受设备、工程语义和桌面状态限制，详见[引擎支持边界](../README.md#已有基础支持但存在限制) |
| 暂未实现 | 利用 `mapping.json` 按 DAW 来源筛选键音、按片段或音符指定转换用途、专用制作底稿视图 |
| 暂未实现 | DAW 工程变更后的增量重渲染与排键合并、缺失设备恢复后的局部补全 |
| 暂未实现 | 多难度共享素材的项目管理、制谱前后音乐事件对照、整套 BMS 作品的发布向导 |

手动排键、长音符、BGM 调整、素材整理和基础检查已可在编辑器内完成。尚未实现的是它们与 DAW 来源信息、增量转换及多难度制作之间的联动。

## 兼容边界

主要迁移缺口已在本轮实现，仍有以下有意保留的差异与验证边界：

- 磁盘清理使用谱面旁的 `.bmse-recovery` 恢复目录，而不是系统回收站或不可恢复的永久删除。恢复时若发现谱面/素材被外部修改或原文件名被占用，会停止而不覆盖新数据。
- LNTYPE 2 导入保持起止时间，但保存为 LNTYPE 1 端点记法。随机分支展开生成独立谱面，不把编辑结果自动折回原分支文本。
- 未展开的条件文件采用完整源文保护：保留原定义和覆盖顺序；画布用于查看/复制，修改通过完整 BMS 文本或展开的独立谱面。不会将分支移到末尾后冒险覆盖原文件。
- iBMSC 工程读取覆盖已核对的 3.x 二进制块格式；不导入该编辑器的撤销历史/界面状态，未知二进制块拒绝读取。传统/扩展列布局需在设置中选对，不能从同名剪贴板头可靠自动判别所有第三方分支。
- 旧 INI 翻译覆盖相同功能键；新增功能若无旧版翻译键，保留简体中文回退文案。Tips 和制作人员文本沿用原始日文。
- 彩蛋采用 Web 重现，保留原 Siromaru 图像与可关闭行为；动画轨迹、旧已废弃特效及日期触发细节不是逐像素复刻。
- 实际第三方播放器本身及操作系统文件选择器仍需用户在本机人工验收；我们已验证其调用协议、取消/错误处理和真实 Wails 桥接，未使用 Computer Use。

未知命令、未知通道和未展开条件块原样保存在扩展区。保存规范化空行与已知字段顺序，不保证字节级保持。单文件上限 32 MiB、200000 对象；每通道最大分割数 1920000。无 BOM 编码不能总被唯一识别，必要时手动重载。

## 代码结构

```text
main.go                    Wails 应用与窗口生命周期
editorservice.go           Go/JS 桥接、原生对话框、设置、素材预览、外部播放器
dawservice.go              DAW 引擎进程、JSON-lines 协议、配置与任务状态
configure-daw.ps1          配置本机 Python/DAW2BMS 路径
build-engine.ps1           打包与验证内置 Python 转换引擎
packaging/                PyInstaller 配置、引擎入口与发布说明
internal/chart/            无 UI 依赖的模型、解析、序列化、编码、校验及测试
internal/storage/          限额读取、Windows 原子替换与测试
frontend/src/model.ts      可测试的编辑、剪贴板、素材引用操作
frontend/src/Editor.tsx     菜单、面板、操作状态与历史
frontend/src/DawImportDialog.tsx  DAW 工程、轨道用途、转换与结果入口
frontend/src/ChartCanvas.tsx Canvas 视口、命中检测、选择与绘制
frontend/src/Controls.tsx   字段提交/取消、模态对话框
frontend/src/api.ts         Wails 适配器与本地 Web 测试适配器
frontend/e2e/              无界面浏览器与真实桥接回归测试
cmd/preview/               仅解析/输出/校验的本地 Web 测试服务
samples/                   原创合成音频与测试谱面
DESIGN.md                  从完成界面提取的设计规范
```

`build/` 中保留了 Wails 脚手架生成的其他平台模板，它们不是已验证的平台支持声明。未使用的模板 public 资源通过 Vite `publicDir: false` 排除在成品之外。

设置与恢复文件默认位于 `%APPDATA%\BMSE-Wails`；测试可通过 `BMSE_CONFIG_DIR` 指定独立目录。试听临时谱面写在原谱面目录，以保证相对素材路径可用。

## 验证记录

- Go 解析/存储测试：Base62 大小写、精确分数、重叠、变拍子、扩展数值、嵌套条件、未知行、编码、容量边界、SPEED 状态隔离、BGM 空列、失败保存和原子替换。
- TypeScript 测试：小节插删、剪贴板精度、2P 轨道、素材重排与交换、LNOBJ/BGA 引用、QuickSend 顺序、未知通道平移。
- 浏览器测试：载入、元数据编辑、Esc 取消、未失焦的新建保护、撤销重做、查找、素材列表键盘隔离、源码应用、写入与对象检查。
- 真正的 Wails 3 server 构建验证 Settings/Parse/Serialize/Validate/SetDirty 桥接；它是测试工具，桌面成品仍是原生 WebView 窗口。
- 1280×900 与 1024×768 截图复查通过，独立界面复查的三项行为/无障碍问题已修复。

## 许可与来源

这是经修改/重写的版本。原 BMSE 作者为 Hayana/UCN-Soft、Drossel Studio、Nekokan_Server，原许可完整保留在 `LICENSE`。Windows 图标沿用原 BMSE.ico，构建副本位于 `build/windows/icon.ico`；测试音由 `samples/create-audio.mjs` 确定性合成。界面图标使用 Lucide，第三方组件分别遵守其自身许可。

Wails 3 官方文档：https://v3.wails.io/ 。
## 本轮补齐（2026-10-28）

- 完整旧配置导入：在设置中选择旧 `bmse.ini`，自动读取同目录的 `lang/`、`theme/`、`shortcut.ini`、`bmse_viewer.ini`；导入后先在设置中检查，保存后生效。播放器相对路径按旧配置目录解析。
- 主题/语言/快捷键：原版三套主题与四种语言打包内置；支持 INI 导入、编辑、导出，按键重复检查。菜单支持 Alt+F/E/V/O/T/H、上下键与 Esc。
- 布局：新增 2P、OCT/FP（13 键、双转盘、脚踏）、独立 1P/2P 转盘位置、轨道背景与各面板显示开关。
- BGA：图像编号、裁剪四角和目标偏移的字段编辑；源画布拖选、目标画布拖动、256×256 实际输出、网格和即时预览。
- 多播放器：新增、删除、排序、选择、配置持久化、旧六行格式导入/导出；所有参数草稿经 JSON 校验再保存。
- 磁盘素材：执行前列出计划，保护同目录其他谱面引用的文件、替代音频扩展名和已有目标；清理移入 `.bmse-recovery`，重命名同步引用和谱面文件；保存恢复记录，支持恢复上次操作，执行中禁止关闭窗口式对话框。
- 兼容读写：iBMSC 3.x 工程导入（已核对公开源码中的 31 字节音符结构）、传统 27 / 扩展 63 列布局选择、修复 xNT 长度列；LNTYPE 2 连续区间导入为 LNTYPE 1 端点。
- 条件分支：选择 RANDOM / SETRANDOM / SWITCH 分支值，支持嵌套 IF / ELSEIF / ELSE、CASE / DEF / SKIP，生成独立可编辑谱面。原文件不被覆盖。
- 检查：LNOBJ 未配对、LN 区间内夹入对象、同轨重叠、同音素材水平重复、结果数量上限与详细统计。
- 辅助功能：原 Tips 文本、SNOW / SIROMARU / STAFFROLL / BSOD 等可关闭彩蛋、命令行打开谱面、打开谱面目录。

本轮没有使用 Computer Use。文件操作回归在临时测试目录实际执行移动/重命名/恢复；播放器测试启动受控子进程验证参数；原生文件选择采用可替换对话框接口验证取消、错误和另存为。无界面浏览器对真实 Wails 服务验证了磁盘操作期间 Esc/× 不会提前关闭。

### 格式参考与本轮验证结果

- iBMSC 工程/剪贴板实现对照：[ChartIO.vb](https://github.com/zardoru/iBMSC/blob/master/iBMSC/ChartIO.vb)、[Note.vb](https://github.com/zardoru/iBMSC/blob/master/iBMSC/Option%20Windows/Note.vb)、[EditorColumns.vb](https://github.com/zardoru/iBMSC/blob/master/iBMSC/EditorColumns.vb)。这些引用只用于核对文件接口，不包含在发行包内。
- 最新验证：Go 全包测试和 `go vet ./...` 通过，39 项前端模型测试、18 项无界面端到端测试通过；Windows 程序重新构建成功。
- 独立界面复查指出的“操作中仍能关闭对话框”和“无效播放器参数被丢弃”已修复并通过对应真实桥接回归。原生主窗口关闭也会在磁盘操作进行中被拦截。
