import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  FilePlus2,
  FolderOpen,
  Save,
  SaveAll,
  RotateCcw,
  Undo2,
  Redo2,
  MousePointer2,
  Pencil,
  Eraser,
  Play,
  Square,
  Search,
  Settings2,
  ArrowUp,
  ArrowDown,
  FileCheck2,
  ChartNoAxesColumn,
  Volume2,
  Trash2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, desktop } from "./api";
import {
  blank,
  configuredBlank,
  playerMode,
  changeMeasure,
  changeBase,
  resizeMeasures,
  cleanDefinitions,
  clipboardRead,
  clipboardWrite,
  copy,
  decode,
  encode,
  eventChannel,
  fingerprint,
  initialSettings,
  keyChannel,
  lanes,
  moveNotes,
  pad,
  quickTargets,
  renumber,
  swapDefinition,
} from "./model";
import {
  findNotes,
  replaceValues,
  quickSend as applyQuickSend,
} from "./editing";
import type {
  Chart,
  Issue,
  Kind,
  Material,
  Mode,
  Note,
  Settings,
} from "./model";
import ChartCanvas from "./ChartCanvas";
import { statistics } from "./statistics";
import { Field, Modal } from "./Controls";
import Preferences from "./Preferences";
import BGAEditor, { BGAImage } from "./BGAEditor";
import AssetDialog from "./AssetDialog";
import DawImportDialog from './DawImportDialog';
import BranchesDialog from "./BranchesDialog";
import Effects from "./Effects";
import MeasureDialog from "./MeasureDialog";
import {
  defaultShortcuts,
  keyCode,
  parseIni,
  shortcutMap,
  themes,
  translateTree,
  translator,
} from "./legacy";
import tipsText from "./legacy/spec/tips.txt?raw";
import "./style.css";

type MenuItem = {
  text: string;
  shortcut?: string;
  action: () => void;
  disabled?: boolean;
};
const encodings = [
  "Auto",
  "System",
  "GBK",
  "Big5",
  "UTF-8 BOM",
  "UTF-8",
  "Shift-JIS",
  "EUC-KR",
  "UTF-16LE",
  "UTF-16BE",
  "UTF-32LE",
  "UTF-32BE",
];
const kindLabels: Record<Kind, string> = {
  normal: "普通",
  invisible: "不可见",
  long: "长音符",
  mine: "地雷",
};
const modeLabels: Record<Mode, string> = {
  select: "编辑",
  write: "写入",
  delete: "删除",
};
export default function Editor() {
  const [initializing, setInitializing] = useState(true);
  const [doc, setDoc] = useState<Chart>(blank),
    [saved, setSaved] = useState(() => fingerprint(blank()));
  const history = useRef<Chart[]>([]),
    future = useRef<Chart[]>([]),
    internalClipboard = useRef("");
  const [selected, setSelected] = useState(new Set<string>()),
    [mode, setMode] = useState<Mode>("select"),
    [kind, setKind] = useState<Kind>("normal");
  const [topTab, setTopTab] = useState("基本"),
    [bottomTab, setBottomTab] = useState("WAV"),
    [material, setMaterial] = useState<Material>("wav"),
    [materialID, setMaterialID] = useState(1);
  const [grid, setGrid] = useState(16),
    [zoom, setZoom] = useState(1),
    [laneZoom, setLaneZoom] = useState(1),
    [player, setPlayer] = useState("SP"),
    [keys, setKeys] = useState(7),
    [scratch, setScratch] = useState("left"),
    [scratch2, setScratch2] = useState("right"),
    [bgm, setBgm] = useState(8);
  const [measure, setMeasure] = useState(0),
    [jumpToken, setJumpToken] = useState(0),
    [cursor, setCursor] = useState({ measure: 0, position: 0, channel: 0 });
  const [menu, setMenu] = useState(""),
    [context, setContext] = useState<{ x: number; y: number } | null>(null),
    [modal, setModal] = useState("");
  const [status, setStatus] = useState("就绪"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [source, setSource] = useState(""),
    [direct, setDirect] = useState("");
  const [settings, setSettings] = useState<Settings>(initialSettings),
    [inputEncoding, setInputEncoding] = useState("Auto"),
    [issues, setIssues] = useState<Issue[]>([]);
  const [preview, setPreview] = useState(""),
    [previewName, setPreviewName] = useState(""),
    [autoPreview, setAutoPreview] = useState(false),
    audio = useRef<HTMLAudioElement>(null);
  const [materialSearch, setMaterialSearch] = useState(""),
    [find, setFind] = useState({
      min: 0,
      max: 999,
      value: "",
      valueTo: "",
      selectedOnly: false,
      channel: "",
      kind: "",
      replacement: "",
    });
  const [recovery, setRecovery] = useState<Chart | null>(null),
    [confirm, setConfirm] = useState<{
      message: string;
      resolve: (v: string) => void;
      save: boolean;
    } | null>(null);
  const [inspected, setInspected] = useState<Note | null>(null),
    fileInput = useRef<HTMLInputElement>(null),
    materialInput = useRef<HTMLInputElement>(null);
  const browserMaterials = useRef(new Map<string, string>()),
    latest = useRef(doc),
    latestDirty = useRef(false),
    ready = useRef(false);
  const [pendingField, setPendingField] = useState(false);
  const documentEpoch = useRef(0),
    settingsRef = useRef(settings);
  settingsRef.current = settings;
  const dirty = fingerprint(doc) !== saved || pendingField;
  latest.current = doc;
  latestDirty.current = dirty;
  const filename = doc.path.split(/[\\/]/).pop() || "Untitled.bms";
  const stats = useMemo(
    () => statistics(doc, player),
    [doc.notes, doc.headers.LNOBJ, doc.base, player],
  );
  useLayoutEffect(
    () => setPlayer(playerMode(doc)),
    [doc.editorMode, doc.headers.PLAYER, doc.headers["OCT/FP"], doc.path],
  );
  const [modalBusy, setModalBusy] = useState(false);
  const [dawSource,setDawSource] = useState('');
  const [assetRenameSource, setAssetRenameSource] = useState("");
  const [tipIndex, setTipIndex] = useState(0),
    [effect, setEffect] = useState("");
  const eggBuffer = useRef("");
  const tips = useMemo(
    () => tipsText.split(/\r?\n\s*\r?\n/).filter(Boolean),
    [],
  );
  const theme = useMemo(
    () =>
      parseIni(
        String(
          settings.ui.themeText ||
            themes[
              String(
                settings.ui.theme ||
                  (player === "OCT"
                    ? "default_oct.ini"
                    : player === "PMS"
                      ? "default_pms.ini"
                      : "default.ini"),
              )
            ],
        ),
      ),
    [settings.ui.themeText, settings.ui.theme, player],
  );
  const t = useMemo(
    () =>
      translator(
        String(settings.ui.language || "chinese_simplified.ini"),
        String(settings.ui.languageText || ""),
      ),
    [settings.ui.language, settings.ui.languageText],
  );
  const applyViewSettings = (s: Settings) => {
    const ui = s.ui;
    if (typeof ui.zoom === "number") setZoom(ui.zoom);
    if (typeof ui.laneZoom === "number") setLaneZoom(ui.laneZoom);
    if (typeof ui.keys === "number") setKeys(ui.keys);
    if (typeof ui.scratch === "string") setScratch(ui.scratch);
    if (typeof ui.scratch2 === "string") setScratch2(ui.scratch2);
    if (typeof ui.autoPreview === "boolean") setAutoPreview(ui.autoPreview);
    if (
      typeof ui.inputEncoding === "string" &&
      encodings.includes(ui.inputEncoding)
    )
      setInputEncoding(ui.inputEncoding);
  };
  const savePreferences = async (s: Settings) => {
    await api.saveSettings(s);
    settingsRef.current = s;
    setSettings(s);
    applyViewSettings(s);
  };
  const loadImage = async (name: string) => {
    const value = desktop
      ? await api.material(doc.path, name)
      : browserMaterials.current.get(name);
    if (!value) throw new Error("请先载入图像素材");
    return value;
  };
  const filesystemTools = async (renameSource = "") => {
    if (!desktop) {
      setError("磁盘素材整理需要桌面版");
      return;
    }
    if (
      (dirty || !doc.path || doc.path.toLowerCase().endsWith(".ibmsc")) &&
      !(await save())
    )
      return;
    setAssetRenameSource(renameSource);
    setModal("assets");
  };
  const branchTools = async () => {
    if (!(await canLeave())) return;
    await run(async () => {
      setSource(await api.serialize(latest.current));
      setModal("branches");
    });
  };
  const update = (d: Chart) => {
    if (fingerprint(d) === fingerprint(latest.current)) return;
    if (
      latest.current.sourceText &&
      d.sourceText === latest.current.sourceText
    ) {
      setError("条件源文保护模式：请通过 BMS 文本编辑，或展开独立分支后编辑。");
      return;
    }
    history.current.push(copy(latest.current));
    const cap = Math.max(
      1,
      Math.min(
        150,
        Math.floor(
          (64 * 1024 * 1024) /
            Math.max(1, fingerprint(latest.current).length * 2),
        ),
      ),
    );
    while (history.current.length > cap) history.current.shift();
    future.current = [];
    latest.current = d;
    documentEpoch.current++;
    setDoc(d);
  };
  const mutate = (fn: (d: Chart) => void) => {
    const d = copy(latest.current);
    fn(d);
    update(d);
  };
  const undo = () => {
    const d = history.current.pop();
    if (d) {
      future.current.push(copy(doc));
      const next = { ...d, path: doc.path };
      latest.current = next;
      documentEpoch.current++;
      setDoc(next);
      setSelected(new Set());
      setStatus("已撤销");
    }
  };
  const redo = () => {
    const d = future.current.pop();
    if (d) {
      history.current.push(copy(doc));
      const next = { ...d, path: doc.path };
      latest.current = next;
      documentEpoch.current++;
      setDoc(next);
      setSelected(new Set());
      setStatus("已重做");
    }
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  const ask = (message: string, save = false) =>
    new Promise<string>((resolve) => setConfirm({ message, resolve, save }));
  const answer = (v: string) => {
    confirm?.resolve(v);
    setConfirm(null);
  };
  const jump = (m: number) => {
    setMeasure(Math.max(0, Math.min(999, m)));
    setJumpToken((v) => v + 1);
  };

  const save = async (as = false): Promise<boolean> => {
    setBusy(true);
    try {
      (document.activeElement as HTMLElement)?.blur?.();
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
      let snapshot = copy(latest.current);
      let path: string;
      if (desktop) {
        const written = await api.saveDocument(snapshot, as);
        if (!written) return false;
        snapshot = written;
        path = written.path;
      } else {
        const encoded = await api.encodeDocument(snapshot);
        const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: "application/octet-stream" }),
          url = URL.createObjectURL(blob),
          link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        path = filename;
      }
      if (!path) return false;
      snapshot.path = path;
      setDoc(snapshot);
      setSaved(fingerprint(snapshot));
      if (!recovery) await api.clearRecovery();
      setSettings(await api.settings());
      setStatus("已保存 " + path);
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const canLeave = async () => {
    (document.activeElement as HTMLElement)?.blur?.();
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve()),
    );
    if (!latestDirty.current) return true;
    const a = await ask("当前谱面有未保存的修改。是否先保存？", true);
    return a === "discard" || (a === "save" && (await save()));
  };
  const install = (d: Chart, unsaved = false) => {
    for (const url of browserMaterials.current.values())
      URL.revokeObjectURL(url);
    browserMaterials.current.clear();
    latest.current = d;
    documentEpoch.current++;
    if (!unsaved && !recovery)
      void api.clearRecovery().catch((e) => setError(String(e)));
    history.current = [];
    future.current = [];
    setDoc(d);
    setSaved(unsaved ? "" : fingerprint(d));
    setSelected(new Set());
    setPreview("");
    setMeasure(0);
    setJumpToken((v) => v + 1);
    setBgm(
      Math.min(
        128,
        Math.max(
          8,
          d.notes.reduce(
            (m, n) => Math.max(m, n.channel >= 1297 ? n.channel - 1296 : 0),
            0,
          ),
        ),
      ),
    );
    setPlayer(playerMode(d));
    setStatus(d.warnings.join(" ") || "就绪");
    setError("");
  };
  const open = async (path = "") => {
    if (!(await canLeave())) return;
    if (!desktop && !path) {
      fileInput.current?.click();
      return;
    }
    await run(async () => {
      const d = await api.open(path, inputEncoding);
      if (d) {
        install(d);
        if (!recovery) await api.clearRecovery();
        setSettings(await api.settings());
      }
    });
  };
  const openBrowserFile = async (file: File) => {
    if (!(await canLeave())) return;
    await run(async () => {
      const bytes = await file.arrayBuffer();
      if (file.name.toLowerCase().endsWith(".ibmsc")) {
        const a = new Uint8Array(bytes);
        let binary = "";
        for (let i = 0; i < a.length; i += 32768)
          binary += String.fromCharCode(...a.subarray(i, i + 32768));
        const d = await api.importIBMSC(
          btoa(binary),
          settings.ui.ibmscColumns === "extended",
        );
        d.path = "";
        install(d, true);
        return;
      }
      const a = new Uint8Array(bytes);
      let binary = "";
      for (let i = 0; i < a.length; i += 32768)
        binary += String.fromCharCode(...a.subarray(i, i + 32768));
      const d = await api.decodeDocument(btoa(binary), inputEncoding);
      d.path = desktop ? "" : file.name;
      install(d, desktop);
    });
  };
  const newFile = async () => {
    if (await canLeave()) {
      const fresh = configuredBlank(settings);
      install(fresh);
      if (!recovery) await api.clearRecovery();
    }
  };
  const remove = () => {
    if (!selected.size) return;
    mutate((d) => (d.notes = d.notes.filter((n) => !selected.has(n.id))));
    setSelected(new Set());
  };
  const copySelected = async (cut = false) => {
    const original = latest.current,
      ids = new Set(selected);
    const text = clipboardWrite(original, ids);
    if (!text) return;
    internalClipboard.current = text;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      setStatus("已复制到编辑器剪贴板");
    }
    if (cut) {
      if (latest.current !== original) {
        setStatus("已复制；文档已变化，未执行剪切删除。");
        return;
      }
      mutate((d) => (d.notes = d.notes.filter((n) => !ids.has(n.id))));
      setSelected(new Set());
    }
  };
  const paste = async () => {
    await run(async () => {
      let text = internalClipboard.current;
      try {
        text = (await navigator.clipboard.readText()) || text;
      } catch {
        /* editor clipboard still works */
      }
      const notes = clipboardRead(
        text,
        doc,
        measure,
        String(settings.ui.ibmscColumns || "standard"),
        scratch,
      );
      if (doc.notes.length + notes.length > 200000)
        throw new Error("对象数量不能超过 200000");
      mutate((d) => (d.notes = d.notes.concat(notes)));
      setSelected(new Set(notes.map((n) => n.id)));
      setStatus(`已粘贴 ${notes.length} 个对象`);
    });
  };
  const inspect = (n: Note) => {
    if (doc.sourceText) {
      setStatus("条件源文保护模式，请使用 BMS 文本编辑");
      return;
    }
    setInspected(copy(n));
    setModal("note");
  };
  const previewMaterial = async (id = materialID) => {
    const name = doc[material][id];
    if (!name) return;
    await run(async () => {
      let source = name;
      if (material === "bga") {
        const parts = name.trim().split(/\s+/);
        source = doc.bmp[decode(parts[0], doc.base)];
      }
      const data = desktop
        ? await api.material(doc.path, source)
        : browserMaterials.current.get(source);
      if (!data)
        throw new Error("浏览器预览需先添加本地素材；桌面版会从谱面目录读取。");
      setPreview(data);
      setPreviewName(source);
      if (material === "wav" && audio.current && preview === data) {
        audio.current.currentTime = 0;
        void audio.current
          .play()
          .catch(() => setStatus("点击播放按钮试听素材"));
      }
    });
  };
  const loadMaterials = async () => {
    if (!desktop) {
      materialInput.current?.click();
      return;
    }
    await run(async () => {
      const files = await api.pick(doc.path, material.toUpperCase());
      if (!files.length) return;
      if (materialID + files.length > doc.base ** 2)
        throw new Error("素材数量超出当前编号进制容量。");
      mutate((d) =>
        files.forEach((file, i) => (d[material][materialID + i] = file)),
      );
    });
  };
  const swapMaterial = (delta: number) => {
    const other = materialID + delta;
    if (other < 1 || other >= doc.base ** 2) return;
    try {
      update(swapDefinition(doc, material, materialID, other));
      setMaterialID(other);
    } catch (e) {
      setError(String(e));
    }
  };
  const validate = () =>
    run(async () => {
      const start = performance.now();
      const result = await api.validate(doc);
      const limit = Number(settings.ui.issueLimit ?? 100);
      setIssues(limit > 0 ? result.slice(0, limit) : result);
      setStatus(
        "检查完成：" +
          result.length +
          " 项" +
          (settings.ui.validatorDetails
            ? ` / ${doc.notes.length} OBJ / ${(performance.now() - start).toFixed(1)} ms`
            : ""),
      );
      setModal("validate");
    });
  const showSource = () =>
    run(async () => {
      const text = await api.serialize(doc);
      sourceBaseline.current = text;
      setSource(text);
      setModal("source");
    });
  const sourceBaseline = useRef("");
  const play = (all: boolean) =>
    run(async () => {
      if (!settings.viewer) {
        setModal("viewer");
        return;
      }
      await api.play(doc, measure, all);
      setStatus(all ? "播放器：从头播放" : `播放器：从 #${pad(measure)} 播放`);
    });
  const quit = async () => {
    if (busy || modalBusy) {
      setStatus("操作进行中，请稍后退出");
      return;
    }
    if (await canLeave()) {
      if (!recovery) await api.clearRecovery();
      await api.quit();
    }
  };

  useEffect(() => {
    let disposed = false;
    let off = () => {};
    let offDrop = () => {};
    (async () => {
      try {
        off = await api.onClose(
          () => closeRef.current(),
          () => setStatus("磁盘操作进行中，请等待完成后退出。"),
        );
        offDrop = await api.onDrop((files) => dropRef.current(files));
        if (disposed) {
          off();
          offDrop();
          return;
        }
        const s = await api.settings();
        if (disposed) return;
        setSettings(s);
        applyViewSettings(s);
        if (s.ui.configurationWarning)
          setError(String(s.ui.configurationWarning));
        if (s.ui.showTips) setModal("tips");
        const ui = s.ui || {};
        if (documentEpoch.current === 0) {
          const fresh = configuredBlank(s);
          latest.current = fresh;
          setDoc(fresh);
          setSaved(fingerprint(fresh));
        }
        if (typeof ui.grid === "number") setGrid(ui.grid);
        if (typeof ui.zoom === "number") setZoom(ui.zoom);
        const r = await api.recovery();
        if (!disposed && r) setRecovery(r);
        if (!disposed && !r && documentEpoch.current === 0) {
          const path = await api.startupPath();
          if (path) {
            const d = await api.open(path, inputEncoding);
            if (d && documentEpoch.current === 0) install(d);
          }
        }
        if (disposed) {
          off();
          offDrop();
        }
      } catch (e) {
        setError(String(e));
      } finally {
        ready.current = true;
        if (!disposed) setInitializing(false);
      }
    })();
    return () => {
      disposed = true;
      off();
      offDrop();
    };
  }, []);
  const closeRef = useRef(quit);
  closeRef.current = quit;
  const dropRef = useRef((files: string[]) => {});
  dropRef.current = (files) => {
    if (initializing || busy || modal || confirm) {
      setStatus("当前操作尚未完成，拖放未处理，请完成后重试。");
      return;
    }
    const file = files.find((p) => /\.(bms|bme|bml|pms|ibmsc)$/i.test(p));
    const dawFile = files.find((p) => /\.(flp|als)$/i.test(p));
    if (dawFile) { setDawSource(dawFile); setModal('daw'); return; }
    if (file) {
      void open(file);
      return;
    }
    if (doc.sourceText) {
      setError("条件源文保护模式不能直接导入素材");
      return;
    }
    void run(async () => {
      const groups: Record<"wav" | "bmp", string[]> = {
        wav: files.filter((p) => /\.(wav|ogg|mp3|flac)$/i.test(p)),
        bmp: files.filter((p) =>
          /\.(bmp|png|jpg|jpeg|gif|webp|mp4|avi)$/i.test(p),
        ),
      };
      for (const paths of Object.values(groups))
        if (materialID + paths.length > doc.base ** 2)
          throw new Error("素材数量超出编号容量");
      const wav = await api.materialPaths(doc.path, groups.wav),
        bmp = await api.materialPaths(doc.path, groups.bmp);
      mutate((d) => {
        wav.forEach((p, i) => (d.wav[materialID + i] = p));
        bmp.forEach((p, i) => (d.bmp[materialID + i] = p));
      });
      setStatus(`已导入 ${wav.length + bmp.length} 个素材`);
    });
  };
  useEffect(() => {
    if (menu)
      document
        .querySelector<HTMLButtonElement>(
          '.dropdown [role="menuitem"]:not(:disabled)',
        )
        ?.focus();
  }, [menu]);
  useEffect(() => {
    const handler = (e: Event) =>
      setPendingField(Boolean((e as CustomEvent<boolean>).detail));
    window.addEventListener("bmse-field-edit", handler);
    return () => window.removeEventListener("bmse-field-edit", handler);
  }, []);
  useEffect(() => {
    document.title = `BMx Sequence Editor 3 — ${filename}${dirty ? " *" : ""}`;
    void api.dirty(dirty, document.title).catch((e) => setError(String(e)));
    const timer = setTimeout(() => {
      if (dirty && !recovery)
        void api
          .backup(doc)
          .catch((e) => setError("恢复备份失败：" + String(e)));
    }, 800);
    return () => clearTimeout(timer);
  }, [doc, dirty, recovery]);
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (latestDirty.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, []);
  useEffect(() => {
    if (!ready.current) return;
    const t = setTimeout(() => {
      const current = settingsRef.current;
      const s = { ...current, ui: { ...current.ui, grid, zoom } };
      void api.saveSettings(s).catch((e) => setError(String(e)));
    }, 500);
    return () => clearTimeout(t);
  }, [grid, zoom]);
  useEffect(() => {
    if (preview && material === "wav")
      void audio.current?.play().catch(() => setStatus("点击播放按钮试听素材"));
  }, [preview]);
  useEffect(() => {
    audio.current?.pause();
    setPreview("");
    if (autoPreview) void previewMaterial(materialID);
    document
      .querySelector<HTMLElement>('.material-list [aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [materialID, material, autoPreview, doc.path]);

  const quickSend = (code: string, all: boolean) => {
    const channel =
      code === "Space"
        ? "bgm"
        : shortcutMap(
            String(settings.ui.shortcuts || defaultShortcuts),
            player,
          )[code];
    if (!channel || !selected.size) return false;
    try {
      const result = applyQuickSend(
        doc,
        selected,
        channel,
        all,
        lanes(player, keys, scratch, bgm, scratch2),
      );
      update(result.doc);
      setSelected(result.selected);
      setBgm(
        Math.min(
          128,
          Math.max(
            bgm,
            result.doc.notes.reduce(
              (m, n) => Math.max(m, n.channel >= 1297 ? n.channel - 1296 : 0),
              0,
            ),
          ),
        ),
      );
    } catch (e) {
      setError(String(e));
    }
    return true;
  };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented || initializing || busy || modal || confirm)
        return;
      if (e.altKey && !e.ctrlKey) {
        const name = (
          {
            f: "文件",
            e: "编辑",
            v: "视图",
            o: "选项",
            t: "工具",
            h: "帮助",
          } as Record<string, string>
        )[e.key.toLowerCase()];
        if (name) {
          e.preventDefault();
          setMenu(name);
          return;
        }
      }
      if (menu) {
        if (e.key === "Escape") {
          e.preventDefault();
          setMenu("");
          return;
        }
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
          e.preventDefault();
          const items = Array.from(
            document.querySelectorAll<HTMLButtonElement>(
              '.dropdown [role="menuitem"]:not(:disabled)',
            ),
          );
          const index = items.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          const next =
            e.key === "Home"
              ? 0
              : e.key === "End"
                ? items.length - 1
                : (index + (e.key === "ArrowDown" ? 1 : -1) + items.length) %
                  items.length;
          items[next]?.focus();
          return;
        }
      }
      const input = (e.target as HTMLElement).closest(
        "input,textarea,select,[contenteditable=true]",
      );
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && ["s", "o", "n", "e", "d"].includes(e.key.toLowerCase())) {
        e.preventDefault();
        (e.target as HTMLElement).blur?.();
        if (e.key.toLowerCase() === "s") void save(e.shiftKey);
        if (e.key.toLowerCase() === "o") void open();
        if (e.key.toLowerCase() === "n") void newFile();
        if (e.key.toLowerCase() === "e" && doc.path) void open(doc.path);
        if (e.key.toLowerCase() === "d" && desktop)
          void run(async () => api.openDirectory(doc.path));
        return;
      }
      if (input) return;
      if (!ctrl && e.key.length === 1)
        eggBuffer.current = (eggBuffer.current + e.key.toUpperCase()).slice(
          -16,
        );
      if (e.key === "Enter") {
        const command = eggBuffer.current
          .trim()
          .replace(/SIROMARU1$/, "SIROMARU")
          .replace(/STAFFROLL2$/, "STAFFROLL");
        eggBuffer.current = "";
        if (command.endsWith("TIPS")) {
          setModal("tips");
          return;
        }
        for (const name of [
          "SIROMARU2",
          "SIROMARU",
          "STAFFROLL",
          "BLUESCREEN",
          "SNOW",
          "BSOD",
          "OFF",
        ])
          if (command.endsWith(name)) {
            setEffect(
              name === "OFF"
                ? ""
                : name === "BSOD"
                  ? "BLUESCREEN"
                  : effect === name
                    ? ""
                    : name,
            );
            return;
          }
      }
      if (e.key === "Escape" && effect) {
        setEffect("");
        return;
      }
      if (ctrl) {
        const action: Record<string, () => void> = {
          z: undo,
          y: redo,
          a: () => setSelected(new Set(doc.notes.map((n) => n.id))),
          c: () => void copySelected(),
          x: () => void copySelected(true),
          v: () => void paste(),
          f: () => setModal("find"),
        };
        if (action[e.key.toLowerCase()]) {
          e.preventDefault();
          action[e.key.toLowerCase()]();
          return;
        }
      }
      const actions: Record<string, () => void> = {
        F1: () => setModal("help"),
        F2: () => setMode("select"),
        F3: () => setMode("write"),
        F4: () => setMode("delete"),
        F5: () => {
          const tabs: Material[] = ["wav", "bmp", "bga"];
          const t = tabs[(tabs.indexOf(material) + 1) % 3];
          setMaterial(t);
          setBottomTab(t.toUpperCase());
        },
        F6: () => void play(true),
        F7: () => void play(false),
        F8: () =>
          void run(async () => {
            await api.stop();
            audio.current?.pause();
          }),
        F11: () => void validate(),
        F12: () => setModal("stats"),
        Delete: remove,
        Escape: () => {
          setSelected(new Set());
          setMenu("");
          setContext(null);
        },
        Home: () => jump(0),
        End: () => jump(doc.notes.reduce((m, n) => Math.max(m, n.measure), 0)),
        PageUp: () => jump(measure + 4),
        PageDown: () => jump(measure - 4),
      };
      if (actions[e.key]) {
        e.preventDefault();
        actions[e.key]();
        return;
      }
      if (
        ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key) &&
        selected.size
      ) {
        e.preventDefault();
        const delta =
          ((e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0) / grid) *
          (e.shiftKey ? 4 : 1);
        update(
          moveNotes(
            doc,
            selected,
            delta,
            e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0,
            lanes(player, keys, scratch, bgm, scratch2),
            grid,
          ),
        );
        return;
      }
      const att = Object.entries(
        parseIni(String(settings.ui.shortcuts || defaultShortcuts)).ATT || {},
      ).find(([, value]) => keyCode(value) === e.code)?.[0];
      if (att) {
        const k = (["normal", "invisible", "long", "mine"] as Kind[])[
          ["NORMAL", "INVISIBLE", "LONGNOTE", "LANDMINE"].indexOf(att)
        ];
        setKind(k);
        const targets = quickTargets(doc, selected, e.shiftKey);
        if (targets.size) {
          mutate((d) =>
            d.notes.forEach((n) => {
              if (targets.has(n.id) && keyChannel(n.channel)) n.kind = k;
            }),
          );
          setSelected(new Set([...selected].filter((id) => !targets.has(id))));
        }
        return;
      }
      if (e.code === "NumpadAdd" || e.code === "NumpadSubtract") {
        e.preventDefault();
        const delta = e.code === "NumpadAdd" ? 1 : -1;
        if (ctrl) swapMaterial(delta);
        else
          setMaterialID((v) =>
            Math.max(
              1,
              Math.min(doc.base ** 2 - 1, v + delta * (e.shiftKey ? 3 : 1)),
            ),
          );
        return;
      }
      if (e.code === "NumpadMultiply") {
        void previewMaterial();
        return;
      }
      if (e.code === "NumpadDivide") {
        audio.current?.pause();
        setPreview("");
        return;
      }
      if (!ctrl && quickSend(e.code, e.shiftKey)) e.preventDefault();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const findMatches = () => findNotes(doc, find, selected);
  const processFind = (action: string) => {
    const ids = findMatches();
    if (action === "select") {
      setSelected(ids);
      setModal("");
      const n = doc.notes.find((n) => ids.has(n.id));
      if (n) jump(n.measure);
    } else if (action === "delete") {
      mutate((d) => (d.notes = d.notes.filter((n) => !ids.has(n.id))));
      setModal("");
    } else {
      try {
        update(replaceValues(doc, ids, find.replacement));
      } catch (e) {
        setError(String(e));
        return;
      }
      setModal("");
    }
    setStatus(`匹配 ${ids.size} 个对象`);
  };
  const menuGroups: Record<string, MenuItem[]> = {
    文件: [
      {
        text: "打开谱面目录",
        shortcut: "Ctrl+D",
        action: () => void run(async () => api.openDirectory(doc.path)),
        disabled: !desktop || !doc.path,
      },
      { text: "新建", shortcut: "Ctrl+N", action: () => void newFile() },
      { text: "打开…", shortcut: "Ctrl+O", action: () => void open() },
      { text: "导入 DAW 工程…", action: () => {setDawSource('');setModal('daw');}, disabled: !desktop },
      {
        text: "重新读取",
        shortcut: "Ctrl+E",
        action: () => void open(doc.path),
        disabled: !desktop || !doc.path,
      },
      { text: "保存", shortcut: "Ctrl+S", action: () => void save() },
      {
        text: "另存为…",
        shortcut: "Ctrl+Shift+S",
        action: () => void save(true),
      },
      { text: "转换向导…", action: () => setModal("convert") },
      ...settings.recent.map((path) => ({
        text: path,
        action: () => void open(path),
      })),
      {
        text: "清空最近文件",
        disabled: !settings.recent.length,
        action: () =>
          void run(async () => {
            await api.clearRecent();
            setSettings(await api.settings());
          }),
      },
      { text: "退出", action: () => void quit(), disabled: !desktop },
    ],
    编辑: [
      {
        text: "撤销",
        shortcut: "Ctrl+Z",
        action: undo,
        disabled: !history.current.length,
      },
      {
        text: "重做",
        shortcut: "Ctrl+Y",
        action: redo,
        disabled: !future.current.length,
      },
      {
        text: "剪切",
        shortcut: "Ctrl+X",
        action: () => void copySelected(true),
        disabled: !selected.size,
      },
      {
        text: "复制",
        shortcut: "Ctrl+C",
        action: () => void copySelected(),
        disabled: !selected.size,
      },
      { text: "粘贴", shortcut: "Ctrl+V", action: () => void paste() },
      {
        text: "删除",
        shortcut: "Del",
        action: remove,
        disabled: !selected.size,
      },
      {
        text: "全选",
        shortcut: "Ctrl+A",
        action: () => setSelected(new Set(doc.notes.map((n) => n.id))),
      },
      {
        text: "查找 / 替换…",
        shortcut: "Ctrl+F",
        action: () => setModal("find"),
      },
      { text: "编辑模式", shortcut: "F2", action: () => setMode("select") },
      { text: "写入模式", shortcut: "F3", action: () => setMode("write") },
      { text: "删除模式", shortcut: "F4", action: () => setMode("delete") },
    ],
    视图: [
      { text: "显示设置", action: () => setTopTab("显示") },
      { text: "返回开头", shortcut: "Home", action: () => jump(0) },
      {
        text: "跳到结尾",
        shortcut: "End",
        action: () =>
          jump(doc.notes.reduce((m, n) => Math.max(m, n.measure), 0)),
      },
      { text: "查看 / 编辑 BMS 文本…", action: () => void showSource() },
    ],
    选项: [
      { text: "主题 / 语言 / 快捷键…", action: () => setModal("preferences") },
      { text: "编码与编号…", action: () => setModal("encoding") },
      {
        text: autoPreview ? "关闭自动试听" : "开启自动试听",
        action: () => setAutoPreview(!autoPreview),
      },
      { text: "播放器设置…", action: () => setModal("viewer") },
    ],
    工具: [
      {
        text: "磁盘素材整理…",
        action: () => void filesystemTools(),
        disabled: !desktop,
      },
      { text: "展开随机 / 条件分支…", action: () => void branchTools() },
      {
        text: "从头播放",
        shortcut: "F6",
        action: () => void play(true),
        disabled: !desktop,
      },
      {
        text: "从当前小节播放",
        shortcut: "F7",
        action: () => void play(false),
        disabled: !desktop,
      },
      {
        text: "停止",
        shortcut: "F8",
        action: () =>
          void run(async () => {
            await api.stop();
          }),
        disabled: !desktop,
      },
      { text: "对象检查…", shortcut: "F11", action: () => void validate() },
      { text: "统计…", shortcut: "F12", action: () => setModal("stats") },
    ],
    帮助: [
      { text: "Tips", action: () => setModal("tips") },
      {
        text: "彩蛋：SNOW",
        action: () => setEffect(effect === "SNOW" ? "" : "SNOW"),
      },
      { text: "停止彩蛋", action: () => setEffect("") },
      { text: "操作帮助", shortcut: "F1", action: () => setModal("help") },
      { text: "关于 BMSE", action: () => setModal("about") },
    ],
  };
  const contextItems: MenuItem[] = [
    ...menuGroups.编辑.slice(2, 7),
    {
      text: `插入 #${pad(cursor.measure)} 小节`,
      action: () => {
        try {
          update(changeMeasure(doc, cursor.measure, true));
        } catch (e) {
          setError(String(e));
        }
      },
    },
    {
      text: `删除 #${pad(cursor.measure)} 小节`,
      action: () => update(changeMeasure(doc, cursor.measure, false)),
    },
  ];
  const Tool = ({
    icon: Icon,
    title,
    action,
    active = false,
    disabled = false,
  }: {
    icon: LucideIcon;
    title: string;
    action: () => void;
    active?: boolean;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      className={`tool ${active ? "active" : ""}`}
      title={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled || busy}
      onClick={action}
    >
      <Icon size={17} strokeWidth={1.6} />
    </button>
  );
  const changeHeader = (key: string, value: string) =>
    mutate((d) => (d.headers[key] = value));
  const materialRows = Array.from(
    {
      length: Math.min(
        doc.base ** 2 - 1,
        Math.max(
          1295,
          materialID + 16,
          ...Object.keys(doc[material]).map(Number),
        ),
      ),
    },
    (_, i) => i + 1,
  ).filter(
    (id) =>
      !materialSearch ||
      `${encode(id, doc.base)} ${doc[material][id] || ""}`
        .toLowerCase()
        .includes(materialSearch.toLowerCase()),
  );

  return translateTree(
    <main
      className="editor"
      aria-busy={busy || initializing}
      onPointerDown={() => {
        if (context) setContext(null);
      }}
    >
      <fieldset className="field-contents" disabled={initializing}>
        <input
          ref={fileInput}
          hidden
          type="file"
          accept=".bms,.bme,.bml,.pms,.ibmsc"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void openBrowserFile(f);
            e.target.value = "";
          }}
        />
        <input
          ref={materialInput}
          hidden
          type="file"
          multiple
          accept={material === "wav" ? "audio/*" : "image/*,video/*"}
          onChange={(e) => {
            const files = [...(e.target.files || [])];
            if (materialID + files.length > doc.base ** 2) {
              setError("素材编号超出范围。");
              return;
            }
            for (const f of files) {
              const old = browserMaterials.current.get(f.name);
              if (old) URL.revokeObjectURL(old);
              browserMaterials.current.set(f.name, URL.createObjectURL(f));
            }
            mutate((d) =>
              files.forEach((f, i) => (d[material][materialID + i] = f.name)),
            );
            e.target.value = "";
          }}
        />
        <nav className="menubar" aria-label="主菜单">
          {Object.keys(menuGroups).map((name) => (
            <div className="menu-host" key={name}>
              <button
                aria-expanded={menu === name}
                onClick={() => setMenu(menu === name ? "" : name)}
              >
                {name}(
                {
                  (
                    {
                      文件: "F",
                      编辑: "E",
                      视图: "V",
                      选项: "O",
                      工具: "T",
                      帮助: "H",
                    } as Record<string, string>
                  )[name]
                }
                )
              </button>
              {menu === name && (
                <>
                  <div className="menu-dismiss" onClick={() => setMenu("")} />
                  <div className="dropdown" role="menu">
                    {menuGroups[name].map((item, i) => (
                      <button
                        role="menuitem"
                        key={i}
                        disabled={item.disabled || busy}
                        onClick={() => {
                          setMenu("");
                          item.action();
                        }}
                      >
                        <span>{item.text}</span>
                        <kbd>{item.shortcut}</kbd>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          ))}
          <span className="app-caption">
            BMx Sequence Editor 3 · {desktop ? "Wails" : "Web 预览"}
          </span>
        </nav>
        <div
          className="toolbar"
          hidden={settings.ui.showToolbar === false}
          role="toolbar"
          aria-label="编辑工具栏"
        >
          <Tool
            icon={FilePlus2}
            title="新建 (Ctrl+N)"
            action={() => void newFile()}
          />
          <Tool
            icon={FolderOpen}
            title="打开 (Ctrl+O)"
            action={() => void open()}
          />
          <Tool
            icon={RotateCcw}
            title="重新读取 (Ctrl+E)"
            action={() => void open(doc.path)}
            disabled={!doc.path || !desktop}
          />
          <Tool icon={Save} title="保存 (Ctrl+S)" action={() => void save()} />
          <Tool
            icon={SaveAll}
            title="另存为 (Ctrl+Shift+S)"
            action={() => void save(true)}
          />
          <i />
          <Tool
            icon={Undo2}
            title="撤销 (Ctrl+Z)"
            action={undo}
            disabled={!history.current.length}
          />
          <Tool
            icon={Redo2}
            title="重做 (Ctrl+Y)"
            action={redo}
            disabled={!future.current.length}
          />
          <i />
          <Tool
            icon={MousePointer2}
            title="编辑 (F2)"
            action={() => setMode("select")}
            active={mode === "select"}
          />
          <Tool
            icon={Pencil}
            title="写入 (F3)"
            action={() => setMode("write")}
            active={mode === "write"}
          />
          <Tool
            icon={Eraser}
            title="删除 (F4)"
            action={() => setMode("delete")}
            active={mode === "delete"}
          />
          <i />
          <label>
            网格{" "}
            <select
              aria-label="网格"
              value={grid}
              onChange={(e) => setGrid(+e.target.value)}
            >
              {[4, 8, 12, 16, 24, 32, 48, 64, 96, 192].map((n) => (
                <option key={n} value={n}>
                  1/{n}
                </option>
              ))}
            </select>
          </label>
          <label>
            高度{" "}
            <select
              aria-label="高度缩放"
              value={zoom}
              onChange={(e) => setZoom(+e.target.value)}
            >
              {[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {Math.round(n * 100)}%
                </option>
              ))}
            </select>
          </label>
          <i />
          <Tool
            icon={Play}
            title="从头播放 (F6)"
            action={() => void play(true)}
            disabled={!desktop}
          />
          <Tool
            icon={Play}
            title="从当前小节播放 (F7)"
            action={() => void play(false)}
            disabled={!desktop}
          />
          <Tool
            icon={Square}
            title="停止 (F8)"
            action={() =>
              void run(async () => {
                audio.current?.pause();
                await api.stop();
              })
            }
            disabled={!desktop}
          />
          <Tool
            icon={Settings2}
            title="播放器设置"
            action={() => setModal("viewer")}
          />
          <i />
          <Tool
            icon={Search}
            title="查找替换 (Ctrl+F)"
            action={() => setModal("find")}
          />
          <Tool
            icon={FileCheck2}
            title="对象检查 (F11)"
            action={() => void validate()}
          />
          <Tool
            icon={ChartNoAxesColumn}
            title="统计 (F12)"
            action={() => setModal("stats")}
          />
          <span className="document-title" title={doc.path}>
            {filename}
            {dirty ? " *" : ""}
          </span>
        </div>
        {error && (
          <div className="error" role="alert">
            <span>{error}</span>
            <button aria-label="关闭错误信息" onClick={() => setError("")}>
              <X size={14} />
            </button>
          </div>
        )}
        {recovery && (
          <div className="recovery">
            <span>
              发现上次未保存的谱面：{recovery.headers.TITLE || "Untitled"}
              。处理前保留旧备份，新编辑请及时保存。
            </span>
            <button
              onClick={() => {
                void (async () => {
                  if (await canLeave()) {
                    install(recovery, true);
                    setRecovery(null);
                  }
                })();
              }}
            >
              恢复
            </button>
            <button
              onClick={() => {
                setRecovery(null);
                if (!latestDirty.current) void api.clearRecovery();
              }}
            >
              放弃备份
            </button>
          </div>
        )}
        {doc.sourceText && (
          <div className="recovery">
            条件源文保护模式：保留分支顺序与定义。请使用“BMS 文本”或“展开随机 /
            条件分支”进行修改。
          </div>
        )}
        <div
          className="workspace"
          data-file-drop-target
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (desktop) return;
            const f = e.dataTransfer.files[0];
            if (f && /\.(bms|bme|bml|pms|ibmsc)$/i.test(f.name))
              void openBrowserFile(f);
          }}
        >
          <aside className="sidebar">
            <div className="tabs" role="tablist" aria-label="信息面板">
              {["基本", "扩展", "显示"].map((t) => (
                <button
                  role="tab"
                  aria-selected={topTab === t}
                  key={t}
                  onClick={() => setTopTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <section
              className="header-panel"
              data-view={topTab === "显示"}
              aria-label={topTab + "信息"}
            >
              <fieldset
                className="field-contents"
                disabled={!!doc.sourceText && topTab !== "显示"}
              >
                {topTab === "基本" && (
                  <>
                    <Field
                      label="标题"
                      value={doc.headers.TITLE || ""}
                      onChange={(v) => changeHeader("TITLE", v)}
                    />
                    <Field
                      label="曲风"
                      value={doc.headers.GENRE || ""}
                      onChange={(v) => changeHeader("GENRE", v)}
                    />
                    <Field
                      label="作者"
                      value={doc.headers.ARTIST || ""}
                      onChange={(v) => changeHeader("ARTIST", v)}
                    />
                    <label className="field">
                      <span>模式</span>
                      <select
                        aria-label="谱面模式"
                        value={player}
                        onChange={(e) => {
                          setPlayer(e.target.value);
                          mutate((d) => {
                            d.editorMode = e.target.value;
                            d.headers.PLAYER =
                              e.target.value === "2P"
                                ? "2"
                                : ["DP", "PMS", "OCT"].includes(e.target.value)
                                  ? "3"
                                  : "1";
                            if (e.target.value === "OCT")
                              d.headers["OCT/FP"] = "1";
                            else delete d.headers["OCT/FP"];
                          });
                        }}
                      >
                        {["SP", "2P", "DP", "PMS", "OCT"].map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </label>
                    <div className="field-pair">
                      <Field
                        label="BPM"
                        type="number"
                        min={0.001}
                        value={doc.headers.BPM || "130"}
                        onChange={(v) => changeHeader("BPM", v)}
                      />
                      <Field
                        label="等级"
                        type="number"
                        min={0}
                        value={doc.headers.PLAYLEVEL || "1"}
                        onChange={(v) => changeHeader("PLAYLEVEL", v)}
                      />
                    </div>
                    <label className="field">
                      <span>判定</span>
                      <select
                        value={doc.headers.RANK || "2"}
                        onChange={(e) => changeHeader("RANK", e.target.value)}
                      >
                        {["Very Hard", "Hard", "Normal", "Easy"].map((v, i) => (
                          <option key={v} value={i}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="field-pair">
                      <Field
                        label="TOTAL"
                        value={doc.headers.TOTAL || ""}
                        onChange={(v) => changeHeader("TOTAL", v)}
                      />
                      <Field
                        label="VOLWAV"
                        value={doc.headers.VOLWAV || ""}
                        onChange={(v) => changeHeader("VOLWAV", v)}
                      />
                    </div>
                  </>
                )}
                {topTab === "扩展" && (
                  <>
                    <Field
                      label="WAV00 地雷音"
                      value={doc.wav[0] || ""}
                      onChange={(v) => mutate((d) => (d.wav[0] = v))}
                    />
                    <Field
                      label="BMP00 MISS"
                      value={doc.bmp[0] || ""}
                      onChange={(v) => mutate((d) => (d.bmp[0] = v))}
                    />
                    {[
                      "SUBTITLE",
                      "SUBARTIST",
                      "STAGEFILE",
                      "BANNER",
                      "BACKBMP",
                      "PREVIEW",
                      "DIFFICULTY",
                      "LNOBJ",
                      "LNMODE",
                      "DEFEXRANK",
                      "COMMENT",
                    ].map((k) => (
                      <Field
                        key={k}
                        label={k}
                        value={doc.headers[k] || ""}
                        onChange={(v) => changeHeader(k, v)}
                      />
                    ))}
                  </>
                )}
                {topTab === "显示" && (
                  <>
                    <label className="field">
                      <span>键数</span>
                      <select
                        value={keys}
                        onChange={(e) => setKeys(+e.target.value)}
                      >
                        <option value={5}>5 / 10 keys</option>
                        <option value={7}>7 / 14 keys</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>1P 转盘</span>
                      <select
                        value={scratch}
                        onChange={(e) => setScratch(e.target.value)}
                      >
                        <option value="left">左侧</option>
                        <option value="right">右侧</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>2P 转盘</span>
                      <select
                        aria-label="2P 转盘"
                        value={scratch2}
                        onChange={(e) => setScratch2(e.target.value)}
                      >
                        <option value="left">左侧</option>
                        <option value="right">右侧</option>
                      </select>
                    </label>
                    <Field
                      label="BGM 列数"
                      type="number"
                      min={1}
                      max={128}
                      value={bgm}
                      onChange={(v) => setBgm(Math.round(+v))}
                    />
                    <label className="field">
                      <span>宽度</span>
                      <select
                        value={laneZoom}
                        onChange={(e) => setLaneZoom(+e.target.value)}
                      >
                        {[0.75, 1, 1.25, 1.5, 2].map((n) => (
                          <option key={n} value={n}>
                            {n * 100}%
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="hint">
                      谱面向上延伸。滚轮纵向移动；Shift + 滚轮横向移动；Ctrl +
                      滚轮缩放。
                    </p>
                    <button
                      onClick={() => {
                        setZoom(1);
                        setLaneZoom(1);
                        setGrid(16);
                        setBgm(8);
                      }}
                    >
                      恢复显示默认值
                    </button>
                  </>
                )}
              </fieldset>
            </section>
            <div
              className="tabs resource-tabs"
              role="tablist"
              aria-label="素材面板"
            >
              {["WAV", "BMP", "BGA", "小节", "扩展"].map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={bottomTab === t}
                  onClick={() => {
                    setBottomTab(t);
                    if (["WAV", "BMP", "BGA"].includes(t)) {
                      setMaterial(t.toLowerCase() as Material);
                      setPreview("");
                    }
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
            {["WAV", "BMP", "BGA"].includes(bottomTab) ? (
              <section className="materials">
                <div className="material-filter">
                  <input
                    aria-label="筛选素材"
                    placeholder="筛选编号 / 文件名"
                    value={materialSearch}
                    onChange={(e) => setMaterialSearch(e.target.value)}
                  />
                  <span>
                    {Object.values(doc[material]).filter(Boolean).length}
                  </span>
                </div>
                <div
                  className="material-list"
                  role="listbox"
                  aria-label={`${bottomTab} 素材列表`}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                      e.preventDefault();
                      e.stopPropagation();
                      setMaterialID((v) =>
                        Math.max(
                          1,
                          Math.min(
                            doc.base ** 2 - 1,
                            v + (e.key === "ArrowDown" ? 1 : -1),
                          ),
                        ),
                      );
                    }
                  }}
                >
                  {materialRows.map((id) => (
                    <div
                      key={id}
                      role="option"
                      aria-selected={id === materialID}
                      className={id === materialID ? "chosen" : ""}
                      onClick={() => {
                        setMaterialID(id);
                      }}
                      onDoubleClick={() => void previewMaterial(id)}
                    >
                      <span>{encode(id, doc.base)}</span>
                      <span>{doc[material][id] || ""}</span>
                    </div>
                  ))}
                </div>
                <div className="material-actions">
                  <button
                    title="重命名素材文件"
                    disabled={
                      !desktop ||
                      material === "bga" ||
                      !doc[material][materialID]
                    }
                    onClick={() =>
                      void filesystemTools(doc[material][materialID])
                    }
                  >
                    改名
                  </button>
                  <button
                    title="添加素材"
                    onClick={() =>
                      material === "bga"
                        ? setModal("bga")
                        : void loadMaterials()
                    }
                    disabled={!!doc.sourceText}
                  >
                    <FolderOpen size={14} />
                    浏览
                  </button>
                  <button
                    title="清空素材定义"
                    onClick={() =>
                      mutate((d) => delete d[material][materialID])
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                  <button title="向上交换编号" onClick={() => swapMaterial(-1)}>
                    <ArrowUp size={14} />
                  </button>
                  <button title="向下交换编号" onClick={() => swapMaterial(1)}>
                    <ArrowDown size={14} />
                  </button>
                  <button
                    title="预览素材"
                    onClick={() => void previewMaterial()}
                  >
                    <Volume2 size={14} />
                  </button>
                </div>
                <Field
                  label={encode(materialID, doc.base)}
                  disabled={!!doc.sourceText}
                  value={doc[material][materialID] || ""}
                  onChange={(v) => mutate((d) => (d[material][materialID] = v))}
                />
                <label className="check">
                  <input
                    type="checkbox"
                    checked={autoPreview}
                    onChange={(e) => setAutoPreview(e.target.checked)}
                  />
                  选中时预览
                </label>
                {preview && (
                  <div className="material-preview">
                    {material === "wav" ? (
                      <audio ref={audio} controls src={preview} />
                    ) : /\.(mp4|avi)$/i.test(previewName) ? (
                      <video controls src={preview} />
                    ) : material === "bga" ? (
                      <BGAImage
                        src={preview}
                        value={doc.bga[materialID] || ""}
                        base={doc.base}
                      />
                    ) : (
                      <img alt={previewName} src={preview} />
                    )}
                    <span title={previewName}>{previewName}</span>
                  </div>
                )}
              </section>
            ) : bottomTab === "小节" ? (
              <section className="measure-panel">
                <div className="measure-list">
                  {Array.from({ length: 1000 }, (_, m) => (
                    <button
                      className={measure === m ? "chosen" : ""}
                      key={m}
                      onClick={() => jump(m)}
                    >
                      #{pad(m)}
                      <span>{doc.measures[m] || 1} × 4/4</span>
                    </button>
                  ))}
                </div>
                <Field
                  label="小节倍率"
                  disabled={!!doc.sourceText}
                  type="number"
                  min={1 / 10000}
                  max={512}
                  value={doc.measures[measure] || 1}
                  onChange={(v) => {
                    try {
                      update(resizeMeasures(doc, measure, measure, +v));
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                />
                <div className="button-row">
                  <button
                    disabled={!!doc.sourceText}
                    onClick={() => setModal("measure")}
                  >
                    批量长度…
                  </button>
                  <button
                    onClick={() => {
                      try {
                        update(changeMeasure(doc, measure, true));
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    插入
                  </button>
                  <button
                    onClick={() => update(changeMeasure(doc, measure, false))}
                  >
                    删除此小节
                  </button>
                </div>
              </section>
            ) : (
              <section className="extra-panel">
                <p className="hint">
                  未知指令与条件分支原样保存。条件分支不在画布中展开。
                </p>
                <textarea
                  aria-label="扩展定义"
                  readOnly={!!doc.sourceText}
                  value={doc.extra.join("\n")}
                  onChange={(e) =>
                    mutate((d) => (d.extra = e.target.value.split("\n")))
                  }
                  spellCheck={false}
                />
              </section>
            )}
          </aside>
          <section className="chart-workspace">
            <div className="chart-tools">
              <label>
                定位{" "}
                <input
                  aria-label="定位小节"
                  type="number"
                  min={0}
                  max={999}
                  value={measure}
                  onChange={(e) => jump(+e.target.value)}
                />
              </label>
              <label>
                属性{" "}
                <select
                  aria-label="对象属性"
                  value={kind}
                  onChange={(e) => {
                    const k = e.target.value as Kind;
                    setKind(k);
                    if (selected.size)
                      mutate((d) =>
                        d.notes.forEach((n) => {
                          if (selected.has(n.id) && keyChannel(n.channel))
                            n.kind = k;
                        }),
                      );
                  }}
                >
                  {Object.entries(kindLabels).map(([k, v], i) => (
                    <option key={k} value={k}>
                      {v} ({i + 1})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                编号{" "}
                <input
                  aria-label="写入编号"
                  value={encode(materialID, doc.base)}
                  maxLength={2}
                  onChange={(e) => {
                    const v = decode(e.target.value, doc.base);
                    if (v > 0 && v < doc.base ** 2) setMaterialID(v);
                  }}
                />
              </label>
              <span>
                {modeLabels[mode]}模式 ·{" "}
                {selected.size
                  ? `选中 ${selected.size} 个对象`
                  : mode === "write"
                    ? "点击网格写入；长音符需写入起点和终点"
                    : "拖动框选；拖动对象移动；右键打开菜单"}
              </span>
            </div>
            <ChartCanvas
              theme={theme}
              readOnly={!!doc.sourceText}
              lockY={settings.ui.yAxisFixed === true}
              scratch2={scratch2}
              laneBackground={settings.ui.laneBackground !== false}
              doc={doc}
              selected={selected}
              setSelected={setSelected}
              commit={update}
              mode={mode}
              kind={kind}
              value={materialID}
              grid={grid}
              zoom={zoom}
              laneZoom={laneZoom}
              player={player}
              keys={keys}
              scratch={scratch}
              bgm={bgm}
              measure={measure}
              jumpToken={jumpToken}
              onCursor={(measure, position, channel) =>
                setCursor({ measure, position, channel })
              }
              onInspect={inspect}
              onContext={(x, y) => setContext({ x, y })}
              onError={setError}
              onZoom={setZoom}
            />
            <Effects effect={effect} onClose={() => setEffect("")} />
            <div
              className="direct-input"
              hidden={settings.ui.showDirectInput === false}
            >
              <label htmlFor="direct">直接输入</label>
              <input
                id="direct"
                value={direct}
                onChange={(e) => setDirect(e.target.value)}
                placeholder="#00111:01000100"
                onKeyDown={(e) => {
                  if (e.key === "Enter")
                    document.getElementById("apply-direct")?.click();
                }}
              />
              <button
                id="apply-direct"
                disabled={!direct.trim()}
                onClick={() =>
                  void run(async () => {
                    const text = await api.serialize(doc);
                    const parsed = await api.parse(text + "\n" + direct);
                    parsed.path = doc.path;
                    parsed.encoding = doc.encoding;
                    if (parsed.headers.PLAYER === doc.headers.PLAYER)
                      parsed.editorMode = doc.editorMode;
                    update(parsed);
                    setDirect("");
                  })
                }
              >
                应用
              </button>
              <button onClick={() => void showSource()}>BMS 文本…</button>
            </div>
          </section>
        </div>
        <footer
          className="statusbar"
          hidden={settings.ui.showStatusBar === false}
        >
          <span className="status-message" title={status}>
            {busy ? "正在处理…" : status}
          </span>
          <span>{modeLabels[mode]}</span>
          <span>
            #{pad(cursor.measure)} : {(cursor.position * 192).toFixed(3)}
          </span>
          <span>CH {encode(cursor.channel, 36)}</span>
          <span>WAV {encode(materialID, doc.base)}</span>
          <span>{doc.notes.length} OBJ</span>
          <span>
            {doc.encoding} / Base {doc.base}
          </span>
        </footer>
        {context && (
          <div
            className="dropdown context-menu"
            role="menu"
            style={{
              left: Math.min(context.x, innerWidth - 270),
              top: Math.min(context.y, innerHeight - 260),
            }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {contextItems.map((item, i) => (
              <button
                role="menuitem"
                key={i}
                disabled={item.disabled}
                onClick={() => {
                  setContext(null);
                  item.action();
                }}
              >
                <span>{item.text}</span>
                <kbd>{item.shortcut}</kbd>
              </button>
            ))}
          </div>
        )}
        {confirm && (
          <Modal title="保存修改" onClose={() => answer("cancel")}>
            <p>{confirm.message}</p>
            <div className="dialog-buttons">
              {confirm.save && (
                <button onClick={() => answer("save")}>保存</button>
              )}
              <button onClick={() => answer("discard")}>
                {confirm.save ? "不保存" : "确定"}
              </button>
              <button autoFocus onClick={() => answer("cancel")}>
                取消
              </button>
            </div>
          </Modal>
        )}
        {modal && (
          <Modal
            title={
              (
                {
                  bga: "BGA 裁剪与偏移",
                  measure: "批量小节长度",
                  preferences: "设置",
                  assets: "磁盘素材整理",
                  branches: "展开随机 / 条件分支",
                  tips: "Tips",
                  note: "对象属性",
                  find: "查找 / 替换",
                  stats: "谱面统计",
                  validate: "对象检查",
                  viewer: "播放器设置",
                  encoding: "编码与编号",
                  source: "BMS 文本",
                  convert: "转换向导",
                  daw: "导入 DAW 工程",
                  help: "操作帮助",
                  about: "关于 BMSE",
                } as Record<string, string>
              )[modal]
            }
            onClose={() => {
              if (!modalBusy && !busy) setModal("");
            }}
            wide={[
              "source",
              "validate",
              "help",
              "preferences",
              "viewer",
              "bga",
              "assets",
              "branches",
              "daw",
            ].includes(modal)}
          >
            {error && (
              <p className="inline-error" role="alert">
                {error}
                <button onClick={() => setError("")}>清除提示</button>
              </p>
            )}
            {modal === 'daw' && <DawImportDialog initialSource={dawSource} onBusy={setModalBusy} onOpen={async (id) => {
              if (!(await canLeave())) return false;
              const generated = await api.dawOpenResult(id);
              install(generated);
              if (!recovery) await api.clearRecovery();
              setSettings(await api.settings());
              setModal('');
              return true;
            }}/>}
            {modal === "note" && inspected && (
              <>
                <Field
                  label="小节"
                  type="number"
                  min={0}
                  max={999}
                  value={inspected.measure}
                  onChange={(v) =>
                    setInspected({ ...inspected, measure: Math.round(+v) })
                  }
                />
                <Field
                  label="位置（0–1）"
                  type="number"
                  min={0}
                  max={0.999999999}
                  value={inspected.position}
                  onChange={(v) =>
                    setInspected({
                      ...inspected,
                      position: +v,
                      numerator: 0,
                      denominator: 0,
                    })
                  }
                />
                <label className="field">
                  <span>轨道</span>
                  <select
                    value={inspected.channel}
                    onChange={(e) =>
                      setInspected({ ...inspected, channel: +e.target.value })
                    }
                  >
                    {lanes(player, keys, scratch, bgm, scratch2).map((l) => (
                      <option key={l.channel} value={l.channel}>
                        {l.label} / {encode(l.channel, 36)}
                      </option>
                    ))}
                  </select>
                </label>
                <Field
                  label={eventChannel(inspected.channel) ? "数值" : "素材编号"}
                  value={
                    eventChannel(inspected.channel)
                      ? inspected.value
                      : encode(
                          inspected.value,
                          inspected.kind === "mine" ? 36 : doc.base,
                        )
                  }
                  onChange={(v) => {
                    const value = eventChannel(inspected.channel)
                      ? Number(v)
                      : decode(v, inspected.kind === "mine" ? 36 : doc.base);
                    if (Number.isFinite(value))
                      setInspected({ ...inspected, value });
                  }}
                />
                <label className="field">
                  <span>属性</span>
                  <select
                    value={inspected.kind}
                    onChange={(e) =>
                      setInspected({
                        ...inspected,
                        kind: e.target.value as Kind,
                      })
                    }
                  >
                    {Object.entries(kindLabels).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="dialog-buttons">
                  <button
                    onClick={() => {
                      mutate(
                        (d) =>
                          (d.notes = d.notes.map((n) =>
                            n.id === inspected.id ? inspected : n,
                          )),
                      );
                      setModal("");
                    }}
                  >
                    确定
                  </button>
                  <button onClick={() => setModal("")}>取消</button>
                </div>
              </>
            )}
            {modal === "find" && (
              <>
                <div className="field-pair">
                  <Field
                    label="起始小节"
                    type="number"
                    min={0}
                    max={999}
                    value={find.min}
                    onChange={(v) => setFind({ ...find, min: +v })}
                  />
                  <Field
                    label="结束小节"
                    type="number"
                    min={0}
                    max={999}
                    value={find.max}
                    onChange={(v) => setFind({ ...find, max: +v })}
                  />
                </div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={find.selectedOnly}
                    onChange={(e) =>
                      setFind({ ...find, selectedOnly: e.target.checked })
                    }
                  />
                  仅在选中对象中查找
                </label>
                <Field
                  label="编号 / 数值上限（可选）"
                  value={find.valueTo}
                  onChange={(v) => setFind({ ...find, valueTo: v })}
                />
                <Field
                  label="编号 / 数值"
                  value={find.value}
                  onChange={(v) => setFind({ ...find, value: v })}
                />
                <label className="field">
                  <span>轨道（Ctrl 多选）</span>
                  <select
                    multiple
                    size={5}
                    value={find.channel ? find.channel.split(",") : [""]}
                    onChange={(e) =>
                      setFind({
                        ...find,
                        channel: Array.from(e.target.selectedOptions)
                          .map((o) => o.value)
                          .filter(Boolean)
                          .join(","),
                      })
                    }
                  >
                    <option value="">所有轨道</option>
                    {lanes(player, keys, scratch, bgm, scratch2).map((l) => (
                      <option key={l.channel} value={l.channel}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>属性</span>
                  <select
                    value={find.kind}
                    onChange={(e) => setFind({ ...find, kind: e.target.value })}
                  >
                    <option value="">所有属性</option>
                    {Object.entries(kindLabels).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <Field
                  label="替换为"
                  value={find.replacement}
                  onChange={(v) => setFind({ ...find, replacement: v })}
                />
                <p>
                  匹配：{findMatches().size} 个对象。编号留空时匹配所有编号。
                </p>
                <div className="dialog-buttons">
                  <button onClick={() => processFind("select")}>选中</button>
                  <button onClick={() => processFind("delete")}>删除</button>
                  <button
                    disabled={!find.replacement}
                    onClick={() => processFind("replace")}
                  >
                    全部替换
                  </button>
                </div>
              </>
            )}
            {modal === "stats" && (
              <>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>类型</th>
                      <th>1P</th>
                      <th>2P</th>
                      <th>总计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(Object.keys(kindLabels) as Kind[]).map((k) => (
                      <tr key={k}>
                        <td>{kindLabels[k]}</td>
                        <td>{stats.sides[0][k]}</td>
                        <td>{stats.sides[1][k]}</td>
                        <td>{stats.sides[0][k] + stats.sides[1][k]}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>可玩音符</td>
                      <td>{stats.total[0]}</td>
                      <td>{stats.total[1]}</td>
                      <td>{stats.total[0] + stats.total[1]}</td>
                    </tr>
                    <tr>
                      <td>BGM</td>
                      <td colSpan={3}>{stats.bgm}</td>
                    </tr>
                    <tr>
                      <td>未配对长音符端点</td>
                      <td colSpan={3}>{stats.unpaired}</td>
                    </tr>
                    <tr>
                      <td>全部对象</td>
                      <td colSpan={3}>{doc.notes.length}</td>
                    </tr>
                  </tbody>
                </table>
                <p className="hint">
                  长音符按配对计为 1 个，包含
                  LNOBJ。可玩音符不含不可见对象和地雷。
                </p>
              </>
            )}
            {modal === "validate" && (
              <>
                <p>
                  {issues.length
                    ? `发现 ${issues.length} 项。点击定位到对应对象。`
                    : "未发现对象重叠、未定义素材或未配对的 LN 通道端点。"}
                </p>
                <div className="issue-list">
                  {issues.map((i, index) => (
                    <button
                      key={index}
                      onClick={() => {
                        jump(i.measure);
                        setSelected(new Set([i.noteId]));
                        setModal("");
                      }}
                    >
                      <span>{i.severity === "error" ? "错误" : "提示"}</span>
                      <code>#{pad(i.measure)}</code>
                      {i.message}
                    </button>
                  ))}
                </div>
                {doc.warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </>
            )}
            {modal === "encoding" && (
              <>
                <label className="field">
                  <span>读取编码</span>
                  <select
                    aria-label="读取编码"
                    value={inputEncoding}
                    onChange={(e) => setInputEncoding(e.target.value)}
                  >
                    {encodings.map((e) => (
                      <option key={e}>{e}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>保存编码</span>
                  <select
                    aria-label="保存编码"
                    value={doc.encoding}
                    onChange={(e) =>
                      mutate((d) => (d.encoding = e.target.value))
                    }
                  >
                    {[...new Set([...encodings.slice(1), doc.encoding])].map(
                      (e) => (
                        <option key={e}>{e}</option>
                      ),
                    )}
                  </select>
                </label>
                <label className="field">
                  <span>素材编号进制</span>
                  <select
                    aria-label="素材编号进制"
                    value={doc.base}
                    onChange={(e) => {
                      try {
                        update(changeBase(doc, +e.target.value));
                        setMaterialID((v) =>
                          Math.min(v, (+e.target.value) ** 2 - 1),
                        );
                      } catch (error) {
                        setError(String(error));
                      }
                    }}
                  >
                    {[16, 36, 62].map((b) => (
                      <option key={b} value={b}>
                        {b} 进制（01–{encode(b * b - 1, b)}）
                      </option>
                    ))}
                  </select>
                </label>
                <p className="hint">
                  自动检测优先 BOM 与有效 UTF-8，其余使用 Shift-JIS。韩文无 BOM
                  文件可手动选择 EUC-KR。不能编码的字符会阻止保存。
                </p>
                <div className="dialog-buttons">
                  <button
                    disabled={!desktop || !doc.path}
                    onClick={() => {
                      setModal("");
                      void open(doc.path);
                    }}
                  >
                    以所选编码重新读取
                  </button>
                  <button onClick={() => setModal("")}>关闭</button>
                </div>
              </>
            )}
            {["viewer", "preferences"].includes(modal) && (
              <Preferences
                onBusy={setModalBusy}
                settings={settings}
                initial={modal === "viewer" ? "播放器" : "主题"}
                onSave={savePreferences}
                onClose={() => setModal("")}
              />
            )}
            {modal === "bga" && (
              <BGAEditor
                doc={doc}
                id={materialID}
                load={loadImage}
                onApply={(value) => mutate((d) => (d.bga[materialID] = value))}
                onClose={() => setModal("")}
              />
            )}
            {modal === "measure" && (
              <MeasureDialog
                doc={doc}
                measure={measure}
                onApply={update}
                onClose={() => setModal("")}
              />
            )}
            {modal === "assets" && (
              <AssetDialog
                renameSource={assetRenameSource}
                onBusy={setModalBusy}
                doc={doc}
                journal={String(settings.ui.lastAssetJournal || "")}
                onResult={async (d, journal) => {
                  install(d);
                  await savePreferences({
                    ...settings,
                    ui: { ...settings.ui, lastAssetJournal: journal },
                  });
                }}
                onClose={() => setModal("")}
              />
            )}
            {modal === "branches" && (
              <BranchesDialog
                onBusy={setModalBusy}
                source={source}
                onApply={(d) => install(d, true)}
                onClose={() => setModal("")}
              />
            )}
            {modal === "tips" && (
              <>
                <pre className="tip-text">{tips[tipIndex % tips.length]}</pre>
                <div className="dialog-buttons">
                  <button
                    onClick={() =>
                      setTipIndex((v) => (v + tips.length - 1) % tips.length)
                    }
                  >
                    上一条
                  </button>
                  <span>
                    {tipIndex + 1} / {tips.length}
                  </span>
                  <button
                    onClick={() => setTipIndex((v) => (v + 1) % tips.length)}
                  >
                    下一条
                  </button>
                  <button onClick={() => setModal("")}>关闭</button>
                </div>
              </>
            )}
            {modal === "source" && (
              <>
                <textarea
                  className="source"
                  aria-label="BMS 源码"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  spellCheck={false}
                />
                <div className="dialog-buttons">
                  <button
                    onClick={() =>
                      void run(async () => {
                        if (source === sourceBaseline.current) {
                          setModal("");
                          return;
                        }
                        const d = await api.parse(source);
                        d.path = doc.path;
                        d.encoding = doc.encoding;
                        if (d.headers.PLAYER === doc.headers.PLAYER)
                          d.editorMode = doc.editorMode;
                        update(d);
                        setSelected(new Set());
                        setModal("");
                      })
                    }
                  >
                    应用到谱面
                  </button>
                  <button onClick={() => setModal("")}>取消</button>
                </div>
              </>
            )}
            {modal === "convert" && (
              <>
                <p>整理当前谱面的素材定义与引用。每项操作均可撤销。</p>
                <div className="conversion-actions">
                  <button
                    onClick={() => {
                      try {
                        update(cleanDefinitions(doc));
                        setModal("");
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    清除未使用的 WAV / BMP / BGA 定义
                  </button>
                  <button
                    onClick={() => {
                      try {
                        update(
                          renumber(
                            doc,
                            material === "bga" ? "bmp" : material,
                            false,
                          ),
                        );
                        setModal("");
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    压缩当前素材列表编号
                  </button>
                  <button
                    onClick={() => {
                      try {
                        update(
                          renumber(
                            doc,
                            material === "bga" ? "bmp" : material,
                            true,
                          ),
                        );
                        setModal("");
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    按文件名排序并重新编号
                  </button>
                </div>
                <p className="hint">
                  文件本身不会被删除或重命名。含条件分支的谱面禁止编号重排。
                </p>
              </>
            )}
            {modal === "help" && (
              <>
                <p>
                  沿用 BMSE 的纵向编辑方式：第 000 小节在底部，时间向上推进。
                </p>
                <table className="data-table">
                  <tbody>
                    {[
                      ["F2 / F3 / F4", "编辑 / 写入 / 删除模式"],
                      ["拖动空白处 / Ctrl 点击", "框选 / 增减选择"],
                      [
                        "拖动选中对象 / 方向键",
                        "移动对象；Shift + 方向键移动 4 格",
                      ],
                      ["1 / 2 / 3 / 4", "普通 / 不可见 / 长音符 / 地雷"],
                      ["A Z S X D C F V", "QuickSend 到 1P 转盘与 7 个键位"],
                      ["B H N J M K , L", "DP 模式 QuickSend 到 2P 键位与转盘"],
                      ["空格", "发送到新的 BGM 轨道"],
                      [
                        "Ctrl+C / X / V",
                        "复制 / 剪切 / 粘贴；兼容 BMSE 与 iBMSC 剪贴板",
                      ],
                      ["Ctrl+Z / Y", "撤销 / 重做"],
                      ["Ctrl+F / F11 / F12", "查找替换 / 对象检查 / 统计"],
                      ["F5 / 小键盘 + -", "切换素材列表 / 改变素材编号"],
                      ["小键盘 * /", "素材预览 / 停止预览"],
                      ["F6 / F7 / F8", "播放器从头播放 / 当前小节播放 / 停止"],
                      [
                        "Home / End / PageUp / PageDown",
                        "开头 / 末尾 / 前进 4 小节 / 后退 4 小节",
                      ],
                    ].map(([k, v]) => (
                      <tr key={k}>
                        <td>
                          <kbd>{k}</kbd>
                        </td>
                        <td>{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p>
                  长音符以两个端点表示，使用“长音符”属性写入起点与终点。双击对象可编辑精确位置与数值。未知通道、随机与条件分支保留在“扩展”文本中。
                </p>
              </>
            )}
            {modal === "about" && (
              <>
                <h2>BMx Sequence Editor 3</h2>
                <p>Web + Wails 3 重写版</p>
                <p>React / TypeScript / Go · Wails 3.0.0</p>
                <p>
                  原项目：Hayana / UCN-Soft、Drossel Studio、Nekokan_Server。
                </p>
                <p>
                  使用许可沿用项目根目录
                  LICENSE。此版本的迁移范围与验证记录见工程 README。
                </p>
              </>
            )}
          </Modal>
        )}
        {(busy || initializing) && (
          <div className="busy-shield" aria-label="正在处理，请稍候" />
        )}
      </fieldset>
    </main>,
    t,
  );
}
