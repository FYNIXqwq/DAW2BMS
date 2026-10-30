import { useRef, useState } from "react";
import type { Settings, Viewer } from "./model";
import { api, desktop } from "./api";
import {
  defaultShortcuts,
  importViewers,
  importLegacy,
  languages,
  parseIni,
  themes,
  translateTree,
  translator,
  validateShortcuts,
} from "./legacy";
import { Field } from "./Controls";

export default function Preferences({
  settings,
  onSave,
  onClose,
  onBusy,
  initial = "主题",
}: {
  settings: Settings;
  onSave: (s: Settings) => Promise<void>;
  onClose: () => void;
  onBusy: (value: boolean) => void;
  initial?: string;
}) {
  const [draft, setDraft] = useState<Settings>(() => ({
    ...settings,
    viewers: settings.viewers?.length
      ? structuredClone(settings.viewers)
      : [
          {
            name: "uBMplay",
            path: settings.viewer,
            playArgs: settings.playArgs,
            allArgs: settings.allArgs,
            stopArgs: settings.stopArgs,
          },
        ],
    selectedViewer: settings.selectedViewer || 0,
  }));
  const [tab, setTab] = useState(initial),
    [error, setError] = useState(""),
    [saving, setSaving] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const [rawArgs, setRawArgs] = useState<Record<string, string>>({});
  const parseArgs = (value: string, name: string) => {
    let v: unknown;
    try {
      v = JSON.parse(value);
    } catch {
      throw new Error(`${name}：参数必须是 JSON 字符串数组`);
    }
    if (!Array.isArray(v) || v.some((x) => typeof x !== "string"))
      throw new Error(`${name}：参数必须是 JSON 字符串数组`);
    return v as string[];
  };
  const validatedPlayers = () =>
    players.map((p, i) => {
      const next = { ...p };
      for (const k of ["allArgs", "playArgs", "stopArgs"] as const)
        next[k] = parseArgs(
          rawArgs[i + ":" + k] ?? JSON.stringify(p[k]),
          p.name + " " + k,
        );
      return next;
    });
  const ui = (key: string, value: unknown) =>
    setDraft({ ...draft, ui: { ...draft.ui, [key]: value } });
  const players = draft.viewers!,
    index = draft.selectedViewer || 0,
    current = players[index];
  const editPlayer = (patch: Partial<Viewer>) =>
    setDraft({
      ...draft,
      viewers: players.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    });
  const field =
    tab === "主题"
      ? "themeText"
      : tab === "语言"
        ? "languageText"
        : "shortcuts";
  const text =
    tab === "主题"
      ? String(
          draft.ui.themeText || themes[String(draft.ui.theme || "default.ini")],
        )
      : tab === "语言"
        ? String(
            draft.ui.languageText ||
              languages[String(draft.ui.language || "chinese_simplified.ini")],
          )
        : String(draft.ui.shortcuts || defaultShortcuts);
  const download = () => {
    const value =
      tab === "播放器"
        ? validatedPlayers()
            .map((p) =>
              [
                p.name,
                p.path,
                p.allArgs.map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" "),
                p.playArgs.map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" "),
                p.stopArgs.join(" "),
                "",
              ].join("\r\n"),
            )
            .join("\r\n")
        : text;
    const url = URL.createObjectURL(
      new Blob([value], { type: "text/plain;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download =
      tab === "播放器"
        ? "bmse_viewer.ini"
        : tab === "快捷键"
          ? "shortcut.ini"
          : tab === "语言"
            ? "language.ini"
            : "theme.ini";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const save = async () => {
    setError("");
    try {
      validateShortcuts(String(draft.ui.shortcuts || defaultShortcuts));
      if (
        draft.ui.themeText &&
        parseIni(String(draft.ui.themeText)).Main?.Key !== "BMSE"
      )
        throw new Error("主题 [Main] Key 必须为 BMSE");
      if (
        draft.ui.languageText &&
        parseIni(String(draft.ui.languageText)).Main?.Key !== "BMSE"
      )
        throw new Error("语言 [Main] Key 必须为 BMSE");
      setSaving(true);
      const parsed = validatedPlayers();
      onBusy(true);
      const p = parsed[index];
      await onSave({
        ...draft,
        viewers: parsed,
        viewer: p.path,
        allArgs: p.allArgs,
        playArgs: p.playArgs,
        stopArgs: p.stopArgs,
      });
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
      onBusy(false);
    }
  };
  const move = (delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= players.length) return;
    const next = [...players];
    [next[index], next[target]] = [next[target], next[index]];
    const raw: Record<string, string> = {};
    for (const [key, value] of Object.entries(rawArgs)) {
      const [i, k] = key.split(":");
      raw[(+i === index ? target : +i === target ? index : i) + ":" + k] =
        value;
    }
    setRawArgs(raw);
    setDraft({ ...draft, viewers: next, selectedViewer: target });
  };
  return translateTree(
    <div className="preferences">
      <div className="tabs" role="tablist" aria-label="设置类别">
        {["主题", "语言", "快捷键", "播放器", "选项"].map((t) => (
          <button
            role="tab"
            key={t}
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <div className="button-row">
        <button
          disabled={!desktop || saving}
          onClick={async () => {
            try {
              setSaving(true);
              const bundle = await api.readLegacy();
              if (Object.keys(bundle).length) {
                setDraft(importLegacy(bundle, draft));
                setRawArgs({});
              }
            } catch (e) {
              setError(String(e));
            } finally {
              setSaving(false);
            }
          }}
        >
          导入旧版完整配置…
        </button>
      </div>
      <input
        hidden
        ref={file}
        type="file"
        accept=".ini,.txt"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          try {
            const buffer = await f.arrayBuffer();
            let text: string;
            try {
              text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
            } catch {
              text = new TextDecoder("shift-jis").decode(buffer);
            }
            if (tab === "播放器") {
              setRawArgs({});
              const imported = importViewers(text);
              if (!imported.length) throw new Error("配置中没有播放器");
              setDraft({ ...draft, viewers: imported, selectedViewer: 0 });
            } else ui(field, text);
          } catch (err) {
            setError(String(err));
          }
          e.target.value = "";
        }}
      />
      {["主题", "语言", "快捷键"].includes(tab) && (
        <>
          {tab !== "快捷键" && (
            <label className="field">
              <span>{tab}</span>
              <select
                aria-label={tab === "主题" ? "主题方案" : "界面语言"}
                value={String(
                  draft.ui[tab === "主题" ? "theme" : "language"] ||
                    (tab === "主题" ? "default.ini" : "chinese_simplified.ini"),
                )}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    ui: {
                      ...draft.ui,
                      [tab === "主题" ? "theme" : "language"]: e.target.value,
                      [field]: "",
                    },
                  })
                }
              >
                {Object.entries({
                  ...(tab === "主题" ? themes : languages),
                  ...(draft.ui[field]
                    ? {
                        [String(
                          draft.ui[tab === "主题" ? "theme" : "language"] ||
                            (tab === "主题"
                              ? "default.ini"
                              : "chinese_simplified.ini"),
                        )]: String(draft.ui[field]),
                      }
                    : {}),
                }).map(([k, v]) => (
                  <option key={k} value={k}>
                    {parseIni(v).Main?.[tab === "主题" ? "Name" : "Language"] ||
                      k}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="button-row">
            <button onClick={() => file.current?.click()}>导入</button>
            <button
              onClick={() => {
                try {
                  download();
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              导出
            </button>
            <button onClick={() => ui(field, "")}>恢复默认</button>
          </div>
          <textarea
            className="config-editor"
            aria-label={tab + " INI"}
            spellCheck={false}
            value={text}
            onChange={(e) => ui(field, e.target.value)}
          />
          <p className="hint">
            保留原 BMSE 的 INI 格式。快捷键使用 A、D1、OemComma
            等原版按键名称。保存后立即生效。
          </p>
        </>
      )}
      {tab === "播放器" && (
        <>
          <label className="field">
            <span>播放器</span>
            <select
              aria-label="播放器列表"
              value={index}
              onChange={(e) =>
                setDraft({ ...draft, selectedViewer: +e.target.value })
              }
            >
              {players.map((p, i) => (
                <option key={i} value={i}>
                  {p.name || `Player ${i + 1}`}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              onClick={() =>
                setDraft({
                  ...draft,
                  viewers: [
                    ...players,
                    {
                      name: "New player",
                      path: "",
                      playArgs: ["<filename>"],
                      allArgs: ["<filename>"],
                      stopArgs: [],
                    },
                  ],
                  selectedViewer: players.length,
                })
              }
            >
              添加
            </button>
            <button
              disabled={players.length === 1}
              onClick={() => {
                const next: Record<string, string> = {};
                for (const [key, value] of Object.entries(rawArgs)) {
                  const [i, k] = key.split(":");
                  if (+i !== index)
                    next[(+i > index ? +i - 1 : +i) + ":" + k] = value;
                }
                setRawArgs(next);
                setDraft({
                  ...draft,
                  viewers: players.filter((_, i) => i !== index),
                  selectedViewer: Math.max(0, index - 1),
                });
              }}
            >
              删除
            </button>
            <button onClick={() => move(-1)}>上移</button>
            <button onClick={() => move(1)}>下移</button>
            <button onClick={() => file.current?.click()}>导入</button>
            <button
              onClick={() => {
                try {
                  download();
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              导出
            </button>
          </div>
          <Field
            label="名称"
            value={current.name}
            onChange={(name) => editPlayer({ name })}
          />
          <Field
            label="播放器路径"
            value={current.path}
            onChange={(path) => editPlayer({ path })}
          />
          <button
            disabled={!desktop}
            onClick={async () => {
              try {
                const path = await api.viewer();
                if (path) editPlayer({ path });
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            浏览播放器…
          </button>
          {(["allArgs", "playArgs", "stopArgs"] as const).map((k, i) => (
            <Field
              key={k}
              label={["从头播放参数", "当前小节参数", "停止参数"][i]}
              value={rawArgs[index + ":" + k] ?? JSON.stringify(current[k])}
              onChange={(v) => {
                setRawArgs((prev) => ({ ...prev, [index + ":" + k]: v }));
                try {
                  parseArgs(v, current.name + " " + k);
                } catch (e) {
                  setError(String(e));
                }
              }}
            />
          ))}
          <p className="hint">
            参数支持 &lt;filename&gt; 和
            &lt;measure&gt;，以独立参数传给播放器。支持原版每六行一个播放器的
            bmse_viewer.ini。
          </p>
        </>
      )}
      {tab === "选项" && (
        <>
          {(
            [
              ["showToolbar", "显示工具栏"],
              ["showDirectInput", "显示直接输入"],
              ["showStatusBar", "显示状态栏"],
              ["laneBackground", "显示轨道背景"],
            ] as const
          ).map(([key, label]) => (
            <label className="check" key={key}>
              <input
                type="checkbox"
                checked={draft.ui[key] !== false}
                onChange={(e) => ui(key, e.target.checked)}
              />
              {label}
            </label>
          ))}
          <label className="field">
            <span>iBMSC 列布局</span>
            <select
              aria-label="iBMSC 列布局"
              value={String(draft.ui.ibmscColumns || "standard")}
              onChange={(e) => ui("ibmscColumns", e.target.value)}
            >
              <option value="extended">扩展布局（BGM 从 63 开始）</option>
              <option value="standard">传统布局（BGM 从 27 开始）</option>
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(draft.ui.showTips)}
              onChange={(e) => ui("showTips", e.target.checked)}
            />
            启动时显示 Tips
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(draft.ui.validatorDetails)}
              onChange={(e) => ui("validatorDetails", e.target.checked)}
            />
            显示详细检查统计
          </label>
          <label className="field">
            <span>检查结果上限</span>
            <input
              aria-label="检查结果上限"
              type="number"
              min={0}
              max={10000}
              value={Number(draft.ui.issueLimit ?? 100)}
              onChange={(e) =>
                ui("issueLimit", Math.max(0, Math.min(10000, +e.target.value)))
              }
            />
          </label>
          <p className="hint">上限 0 表示显示全部结果。</p>
        </>
      )}
      <div className="dialog-buttons">
        <button disabled={saving} onClick={() => void save()}>
          保存设置
        </button>
        <button disabled={saving} onClick={onClose}>
          取消
        </button>
      </div>
    </div>,
    translator(
      String(draft.ui.language || "chinese_simplified.ini"),
      String(draft.ui.languageText || ""),
    ),
  );
}
