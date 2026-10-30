import React from "react";
import type { Lane, Viewer, Settings } from "./model";

export type Ini = Record<string, Record<string, string>>;
export function parseIni(text: string): Ini {
  const result: Ini = Object.create(null);
  let section = "";
  for (const raw of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^[;#]/.test(line)) continue;
    const head = /^\[(.*)\]$/.exec(line);
    if (head) {
      section = head[1];
      result[section] ??= Object.create(null);
      continue;
    }
    const at = line.indexOf("=");
    if (at < 0) continue;
    let value = line.slice(at + 1).trim();
    if (value.startsWith('"') && value.endsWith('"'))
      value = value.slice(1, -1);
    (result[section] ??= Object.create(null))[line.slice(0, at).trim()] = value;
  }
  return result;
}
const themeFiles = import.meta.glob("./legacy/theme/*.ini", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
const languageFiles = import.meta.glob("./legacy/lang/*.ini", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
const named = (files: Record<string, string>) =>
  Object.fromEntries(
    Object.entries(files).map(([k, v]) => [k.split("/").pop()!, v]),
  );
export const themes = named(themeFiles),
  languages = named(languageFiles);
export const defaultShortcuts = `[ATT]
NORMAL=D1
INVISIBLE=D2
LONGNOTE=D3
LANDMINE=D4
[SP]
SC=A
KEY1=Z
KEY2=S
KEY3=X
KEY4=D
KEY5=C
KEY6=F
KEY7=V
[DP]
1P_SC=A
1P_KEY1=Z
1P_KEY2=S
1P_KEY3=X
1P_KEY4=D
1P_KEY5=C
1P_KEY6=F
1P_KEY7=V
2P_KEY1=B
2P_KEY2=H
2P_KEY3=N
2P_KEY4=J
2P_KEY5=M
2P_KEY6=K
2P_KEY7=OemComma
2P_SC=L
[PMS]
KEY1=Z
KEY2=S
KEY3=X
KEY4=D
KEY5=C
KEY6=F
KEY7=V
KEY8=G
KEY9=B
[OCT/FP]
FOOT=Q
LSC=A
KEY1=Z
KEY2=S
KEY3=X
KEY4=D
KEY5=C
KEY6=F
KEY7=V
KEY8=G
KEY9=B
KEY10=H
KEY11=N
KEY12=J
KEY13=M
RSC=K
`;
export function keyCode(value: string): string {
  if (/^[A-Z]$/i.test(value)) return "Key" + value.toUpperCase();
  if (/^D\d$/i.test(value)) return "Digit" + value.slice(1);
  const aliases: Record<string, string> = {
    OemComma: "Comma",
    OemPeriod: "Period",
    OemMinus: "Minus",
    Oemplus: "Equal",
    Return: "Enter",
    Space: "Space",
    Add: "NumpadAdd",
    Subtract: "NumpadSubtract",
    Multiply: "NumpadMultiply",
    Divide: "NumpadDivide",
  };
  return aliases[value] || value;
}
export function shortcutMap(
  text: string,
  mode: string,
): Record<string, number> {
  const ini = parseIni(text || defaultShortcuts),
    section =
      ini[mode === "OCT" ? "OCT/FP" : mode === "2P" ? "DP" : mode] || {};
  const keys = [37, 38, 39, 40, 41, 44, 45],
    pms = [37, 38, 39, 40, 41, 74, 75, 76, 77],
    oct = [...keys, 74, 75, 76, 77, 80, 81];
  const result: Record<string, number> = {};
  for (const [name, value] of Object.entries(section)) {
    let channel = 0;
    const match = /^(?:(1P|2P)_)?KEY(\d+)$/.exec(name);
    if (match) {
      const index = +match[2] - 1;
      channel =
        mode === "PMS"
          ? pms[index]
          : mode === "OCT"
            ? oct[index]
            : (keys[index] || 0) + (match[1] === "2P" ? 36 : 0);
    } else
      channel =
        (
          {
            SC: 42,
            "1P_SC": 42,
            "2P_SC": 78,
            LSC: 42,
            RSC: 78,
            FOOT: 73,
          } as Record<string, number>
        )[name] || 0;
    if (channel) result[keyCode(value)] = channel;
  }
  return result;
}
export function validateShortcuts(text: string) {
  const ini = parseIni(text);
  for (const name of ["SP", "DP", "PMS", "OCT/FP", "ATT"]) {
    const entries = Object.values(ini[name] || {}).map(keyCode);
    if (new Set(entries).size !== entries.length)
      throw new Error(`${name}: 快捷键重复`);
    if (
      entries.some(
        (v) =>
          !/^Key[A-Z]$|^Digit\d$|^Numpad\d$|^F\d{1,2}$|^(Space|Comma|Period|Slash|Semicolon|Quote|BracketLeft|BracketRight|Minus|Equal)$/.test(
            v,
          ),
      )
    )
      throw new Error(`${name}: 不支持的按键名称`);
  }
  return text;
}
export function color(
  ini: Ini,
  section: string,
  key: string,
  fallback: string,
) {
  const raw = ini[section]?.[key];
  if (!raw) return fallback;
  if (/^#[\da-f]{6}$/i.test(raw)) return raw;
  const p = raw.split(",").map(Number);
  return p.length === 3 &&
    p.every((v) => Number.isFinite(v) && v >= 0 && v <= 255)
    ? `rgb(${p.join(",")})`
    : fallback;
}
export function laneTheme(l: Lane, ini: Ini): Lane {
  let section =
    l.channel >= 1297
      ? "BGM"
      : [4, 6, 7].includes(l.channel)
        ? "BGA"
        : [8, 9, 1020, 1033].includes(l.channel)
          ? "BPM"
          : "";
  if (!section) {
    const side = l.channel >= 73 ? 2 : 1,
      key = l.channel - side * 36;
    section = `KEY_${side}P_${key === 6 ? "SC" : String(key === 8 ? 6 : key === 9 ? 7 : key).padStart(2, "0")}`;
  }
  let text: string | undefined = ini[section]?.Text;
  if (section === "BPM" && text)
    text = text.split(",")[[1033, 1020, 8, 9].indexOf(l.channel)];
  if (["BGA", "BGM"].includes(section)) text = undefined;
  return {
    ...l,
    bg: color(ini, section, "Background", l.bg),
    color: color(ini, section, "ObjectLight", l.color),
    label: text || l.label,
  };
}
export function splitArgs(line: string): string[] {
  const result: string[] = [];
  let word = "",
    quoted = false;
  for (const c of line.trim()) {
    if (c === '"') {
      quoted = !quoted;
      continue;
    }
    if (/\s/.test(c) && !quoted) {
      if (word) {
        result.push(word);
        word = "";
      }
    } else word += c;
  }
  if (quoted) throw new Error("播放器参数存在未配对引号");
  if (word) result.push(word);
  return result;
}
export function importViewers(text: string): Viewer[] {
  const lines = text
    .replace(/^\uFEFF/, "")
    .replace(/\r/g, "")
    .split("\n");
  const result: Viewer[] = [];
  for (let i = 0; i + 4 < lines.length; i += 6) {
    if (!lines[i].trim() && !lines[i + 1].trim()) continue;
    result.push({
      name: lines[i],
      path: lines[i + 1],
      allArgs: splitArgs(lines[i + 2]),
      playArgs: splitArgs(lines[i + 3]),
      stopArgs: splitArgs(lines[i + 4]),
    });
  }
  return result;
}

export function importLegacy(
  bundle: Record<string, string>,
  settings: Settings,
): Settings {
  const c = parseIni(bundle["bmse.ini"] || "");
  if (c.Main?.Key !== "BMSE") throw new Error("不是有效的 bmse.ini");
  const main = c.Main,
    view = c.View || {},
    options = c.Options || {};
  const next = structuredClone(settings);
  const bool = (v: string | undefined, fallback: boolean) =>
    v === undefined ? fallback : /^(true|1|-1)$/i.test(v);
  const num = (v: string | undefined, def: number, min: number, max: number) =>
    Number.isFinite(Number(v)) && v !== undefined
      ? Math.max(min, Math.min(max, Number(v)))
      : def;
  next.ui = {
    ...next.ui,
    theme: main.Theme || "default.ini",
    themeText: bundle["theme/" + main.Theme] || "",
    language: main.Language || "english.ini",
    languageText: bundle["lang/" + main.Language] || "",
    shortcuts: bundle["shortcut.ini"] || defaultShortcuts,
    zoom: num(view.Height, 100, 25, 300) / 100,
    laneZoom: num(view.Width, 100, 50, 300) / 100,
    keys: view.Key === "0" ? 5 : 7,
    scratch: view.SC_1P === "1" ? "right" : "left",
    scratch2: view.SC_2P === "0" ? "left" : "right",
    autoPreview: bool(options.SelectSound, false),
    showToolbar: bool(view.ToolBar, true),
    showDirectInput: bool(view.DirectInput, true),
    showStatusBar: bool(view.StatusBar, true),
    laneBackground: bool(options.LaneBG, true),
    fileNameOnly: bool(options.FileNameOnly, false),
    defaultBase: num(options.BaseNumber, 36, 16, 62),
    inputEncoding:
      ({ SJIS: "Shift-JIS", SYS: "System" } as Record<string, string>)[
        options.InputEncoding
      ] ||
      options.InputEncoding ||
      "Auto",
    outputEncoding:
      options.OutputEncoding === "UTF-8"
        ? "UTF-8 BOM"
        : ({ SJIS: "Shift-JIS", SYS: "System" } as Record<string, string>)[
            options.OutputEncoding
          ] ||
          options.OutputEncoding ||
          "UTF-8",
    legacyImported: true,
  };
  const profiles = bundle["bmse_viewer.ini"]
    ? importViewers(bundle["bmse_viewer.ini"])
    : [];
  if (profiles.length) {
    if (bundle.baseDirectory)
      for (const p of profiles) {
        if (p.path && !/^(?:[a-z]:[\\/]|\\\\|\/)/i.test(p.path))
          p.path = bundle.baseDirectory.replace(/[\\/]$/, "") + "\\" + p.path;
      }
    next.viewers = profiles;
    next.selectedViewer = num(view.ViewerNum, 0, 0, profiles.length - 1);
    const p = profiles[next.selectedViewer];
    next.viewer = p.path;
    next.playArgs = p.playArgs;
    next.allArgs = p.allArgs;
    next.stopArgs = p.stopArgs;
  }
  return next;
}

const clean = (s: string) =>
  s
    .replace(/\(&[A-Za-z]\)/g, "")
    .replace(/&/g, "")
    .replace(/[.…]+$/g, "")
    .trim();
const aliases: Record<string, string> = {
  文件: "Menu.FILE",
  编辑: "Menu.EDIT",
  视图: "Menu.VIEW",
  选项: "Menu.OPTIONS",
  工具: "Menu.TOOLS",
  帮助: "Menu.HELP",
  新建: "Menu.FILE_NEW",
  打开: "Menu.FILE_OPEN",
  保存: "Menu.FILE_SAVE",
  另存为: "Menu.FILE_SAVE_AS",
  重新读取: "Menu.FILE_RELOAD",
  退出: "Menu.FILE_EXIT",
  撤销: "Menu.EDIT_UNDO",
  重做: "Menu.EDIT_REDO",
  剪切: "Menu.EDIT_CUT",
  复制: "Menu.EDIT_COPY",
  粘贴: "Menu.EDIT_PASTE",
  删除: "Menu.EDIT_DELETE",
  全选: "Menu.EDIT_SELECT_ALL",
  "查找 / 替换": "Menu.EDIT_FIND",
  查找替换: "Menu.EDIT_FIND",
  查找: "Menu.EDIT_FIND",
  转换向导: "Menu.FILE_CONVERT_WIZARD",
  对象检查: "Menu.EDIT_OBJECT_VALIDATOR",
  统计: "Menu.EDIT_STATISTICS",
  谱面统计: "Menu.EDIT_STATISTICS",
  播放器设置: "Menu.TOOLS_SETTING",
  从头播放: "Menu.TOOLS_PLAY_ALL",
  从当前小节播放: "Menu.TOOLS_PLAY",
  停止: "Menu.TOOLS_STOP",
  标题: "Header.BASIC_TITLE",
  曲风: "Header.BASIC_GENRE",
  作者: "Header.BASIC_ARTIST",
  模式: "Header.BASIC_PLAYER",
  等级: "Header.BASIC_PLAYLEVEL",
  判定: "Header.BASIC_RANK",
};
const extra: Record<string, string[]> = {
  "主题 / 语言 / 快捷键": [
    "Theme / Language / Shortcuts",
    "テーマ / 言語 / キー設定",
    "테마 / 언어 / 단축키",
  ],
  界面语言: ["Interface language", "表示言語", "표시 언어"],
  主题方案: ["Theme preset", "テーマ選択", "테마 선택"],
  磁盘素材整理: ["Manage material files", "素材ファイル整理", "소재 파일 관리"],
  "展开随机 / 条件分支": [
    "Resolve random / conditional branches",
    "ランダム分岐を展開",
    "랜덤 / 조건 분기 펼치기",
  ],
  "BGA 裁剪与偏移": [
    "BGA crop and offset",
    "BGA 切り抜きと位置",
    "BGA 자르기 및 위치",
  ],
  恢复默认: ["Reset defaults", "初期値に戻す", "기본값 복원"],
  播放器路径: ["Player executable", "プレイヤーパス", "플레이어 경로"],
  名称: ["Name", "名前", "이름"],
  就绪: ["Ready", "準備完了", "준비"],
  基本: ["Basic", "基本", "기본"],
  扩展: ["Extended", "拡張", "확장"],
  显示: ["Display", "表示", "표시"],
  小节: ["Measures", "小節", "마디"],
  设置: ["Settings", "設定", "설정"],
  主题: ["Theme", "テーマ", "테마"],
  语言: ["Language", "言語", "언어"],
  快捷键: ["Shortcuts", "ショートカット", "단축키"],
  播放器: ["Players", "プレイヤー", "플레이어"],
  确定: ["OK", "OK", "확인"],
  取消: ["Cancel", "キャンセル", "취소"],
  关闭: ["Close", "閉じる", "닫기"],
  应用: ["Apply", "適用", "적용"],
  浏览: ["Browse", "参照", "찾기"],
  添加: ["Add", "追加", "추가"],
  上移: ["Move up", "上へ", "위로"],
  下移: ["Move down", "下へ", "아래로"],
  保存设置: ["Save settings", "設定を保存", "설정 저장"],
  选中: ["Select", "選択", "선택"],
  全部替换: ["Replace all", "すべて置換", "모두 바꾸기"],
  普通: ["Normal", "通常", "일반"],
  不可见: ["Invisible", "不可視", "숨김"],
  长音符: ["Long note", "ロングノート", "롱노트"],
  地雷: ["Mine", "地雷", "지뢰"],
  导入: ["Import", "インポート", "가져오기"],
  导出: ["Export", "エクスポート", "내보내기"],
  操作帮助: ["Help", "操作ヘルプ", "도움말"],
  恢复: ["Restore", "復元", "복원"],
  不保存: ["Discard", "保存しない", "저장 안 함"],
  保存修改: ["Save changes", "変更を保存", "변경 저장"],
  "导入 DAW 工程": ["Import DAW project", "DAW プロジェクトを読み込む", "DAW 프로젝트 가져오기"],
};
export function translator(language: string, custom = "") {
  if (language === "chinese_simplified.ini" && !custom) return (s: string) => s;
  const ini = parseIni(
      custom || languages[language] || languages["english.ini"],
    ),
    zh = parseIni(languages["chinese_simplified.ini"]);
  const dictionary = new Map<string, string>();
  for (const [section, values] of Object.entries(zh))
    for (const [key, value] of Object.entries(values)) {
      const target = ini[section]?.[key];
      if (target) dictionary.set(clean(value), clean(target));
    }
  for (const [label, path] of Object.entries(aliases)) {
    const [section, key] = path.split(".");
    if (ini[section]?.[key]) dictionary.set(label, clean(ini[section][key]));
  }
  const langIndex =
    language === "chinese_simplified.ini"
      ? -1
      : language === "japanese.ini"
        ? 1
        : language === "korean.ini"
          ? 2
          : 0;
  for (const [k, v] of Object.entries(extra))
    if (!dictionary.has(k)) dictionary.set(k, langIndex < 0 ? k : v[langIndex]);
  return (s: string) => {
    const exact = dictionary.get(clean(s));
    if (exact) return exact + (/[.…]$/.test(s) ? "…" : "");
    const match = /^(.*?)(\s*\([^)]*\))$/.exec(s);
    if (match && dictionary.has(clean(match[1])))
      return dictionary.get(clean(match[1])) + match[2];
    return s;
  };
}
// Translate React nodes, never the DOM. Controlled values, IDs and event handlers remain untouched.
export function translateTree(
  node: React.ReactNode,
  t: (s: string) => string,
): React.ReactNode {
  if (typeof node === "string") return t(node);
  if (Array.isArray(node)) return node.map((n) => translateTree(n, t));
  if (!React.isValidElement(node)) return node;
  const props = node.props as Record<string, unknown>,
    patch: Record<string, unknown> = {};
  for (const key of ["title", "label", "aria-label", "placeholder"])
    if (typeof props[key] === "string") patch[key] = t(props[key] as string);
  if (
    node.type === "option" &&
    props.value === undefined &&
    typeof props.children === "string"
  )
    patch.value = props.children;
  if (props.children !== undefined)
    patch.children = translateTree(props.children as React.ReactNode, t);
  return React.cloneElement(
    node as React.ReactElement<Record<string, unknown>>,
    patch,
  );
}
