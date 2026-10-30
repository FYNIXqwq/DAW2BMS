import type { Chart, Issue, Settings } from "./model";
import { initialSettings, normalizeSettings } from "./model";
import type { DawConfig, DawPreview, DawJob, DawRequest } from './daw';

export const desktop =
  !location.href.startsWith("http://127.0.0.1:9246") &&
  !new URLSearchParams(location.search).has("web");
let runtime: Promise<typeof import("@wailsio/runtime")> | undefined;
const rt = () => (runtime ??= import("@wailsio/runtime"));
let revision = 0;
function nextRevision() {
  revision = Math.max(
    Date.now(),
    revision + 1,
    (Number(localStorage.getItem("bmse-recovery-revision")) || 0) + 1,
  );
  return revision;
}
async function call<T>(name: string, ...args: unknown[]): Promise<T> {
  if (desktop)
    return (await rt()).Call.ByName("main.EditorService." + name, ...args);
  if (
    [
      "Parse",
      "Serialize",
      "Validate",
      "Branches",
      "ResolveBranches",
      "ImportIBMSC",
      "DecodeDocument",
      "EncodeDocument",
    ].includes(name)
  ) {
    const response = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args.length > 1 ? args : args[0]),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    return result;
  }
  if (name === "Settings") {
    try {
      return JSON.parse(
        localStorage.getItem("bmse-settings") ||
          JSON.stringify(initialSettings),
      );
    } catch {
      return {
        ...initialSettings,
        ui: { configurationWarning: "配置无效，已使用默认设置。" },
      } as T;
    }
  }
  if (name === "ClearRecent") {
    const settings = normalizeSettings(
      JSON.parse(localStorage.getItem("bmse-settings") || "{}"),
    );
    settings.recent = [];
    localStorage.setItem("bmse-settings", JSON.stringify(settings));
    return undefined as T;
  }
  if (name === "SaveSettings") {
    localStorage.setItem("bmse-settings", JSON.stringify(args[0]));
    return undefined as T;
  }
  if (name === "Recovery")
    return JSON.parse(localStorage.getItem("bmse-recovery") || "null");
  if (name === "BackupVersioned" || name === "ClearRecoveryVersioned") {
    const value = Number(args[name === "BackupVersioned" ? 1 : 0]);
    if (value <= Number(localStorage.getItem("bmse-recovery-revision") || 0))
      return undefined as T;
    if (name === "BackupVersioned")
      localStorage.setItem("bmse-recovery", JSON.stringify(args[0]));
    else localStorage.removeItem("bmse-recovery");
    localStorage.setItem("bmse-recovery-revision", String(value));
    return undefined as T;
  }
  if (name === "Backup") {
    localStorage.setItem("bmse-recovery", JSON.stringify(args[0]));
    return undefined as T;
  }
  if (name === "ClearRecovery") {
    localStorage.removeItem("bmse-recovery");
    return undefined as T;
  }
  if (name === "SetDirty") return undefined as T;
  if (name === "StartupPath") return "" as T;
  throw new Error("此操作需要 Wails 桌面版。");
}
export const api = {
  dawSettings: () => call<DawConfig>('DawSettings'),
  dawSaveSettings: (config: DawConfig) => call<void>('DawSaveSettings',config),
  dawPick: (kind: string) => call<string>('DawPick',kind),
  dawInspect: (source: string,language: string) => call<DawPreview>('DawInspect',source,language),
  dawStart: (request: DawRequest) => call<DawJob>('DawStart',request),
  dawStatus: () => call<DawJob|null>('DawStatus'),
  dawCancel: (id: string) => call<void>('DawCancel',id),
  dawOpenResult: (id: string) => call<Chart>('DawOpenResult',id),
  dawOpenOutput: (id: string) => call<void>('DawOpenOutput',id),
  decodeDocument: (data: string, encoding: string) =>
    call<Chart>("DecodeDocument", data, encoding),
  encodeDocument: (doc: Chart) => call<string>("EncodeDocument", doc),
  saveDocument: (doc: Chart, as = false) =>
    call<Chart | null>("SaveDocument", doc, as),
  onDrop: async (fn: (files: string[]) => void) =>
    desktop
      ? (await rt()).Events.On("files-dropped", (event) =>
          fn((event.data as { files: string[] }).files),
        )
      : () => {},
  startupPath: () => call<string>("StartupPath"),
  openDirectory: (path: string) => call<void>("OpenDirectory", path),
  readLegacy: () => call<Record<string, string>>("ReadLegacy", ""),
  branches: (text: string) =>
    call<{ line: number; maximum: number; fixed: number; kind: string }[]>(
      "Branches",
      text,
    ),
  resolveBranches: (text: string, choices: Record<number, number>) =>
    call<Chart>("ResolveBranches", text, choices),
  importIBMSC: (data: string, extended: boolean) =>
    call<Chart>("ImportIBMSC", data, extended),
  planAssets: (doc: Chart, mode: string) =>
    call<AssetPlan>("PlanAssets", doc, mode),
  planRename: (doc: Chart, from: string, to: string) =>
    call<AssetPlan>("PlanRename", doc, from, to),
  applyAssets: (token: string) =>
    call<{ document: Chart; journal: string; count: number }>(
      "ApplyAssets",
      token,
    ),
  restoreAssets: (path: string, chartPath: string) =>
    call<Chart>("RestoreAssetsForChart", path, chartPath),
  open: (path = "", encoding = "Auto") =>
    call<Chart | null>("Open", path, encoding),
  parse: (text: string) => call<Chart>("Parse", text),
  serialize: (d: Chart) => call<string>("Serialize", d),
  save: (d: Chart, as = false) => call<string>("Save", d, as),
  validate: (d: Chart) => call<Issue[]>("Validate", d),
  settings: () => call<Settings>("Settings").then(normalizeSettings),
  clearRecent: () => call<void>("ClearRecent"),
  saveSettings: (s: Settings) => call<void>("SaveSettings", s),
  dirty: (dirty: boolean, title: string) =>
    call<void>("SetDirty", dirty, title),
  backup: (d: Chart) => call<void>("BackupVersioned", d, nextRevision()),
  recovery: () => call<Chart | null>("Recovery"),
  clearRecovery: () => call<void>("ClearRecoveryVersioned", nextRevision()),
  pick: (path: string, kind: string) =>
    call<string[]>("PickMaterials", path, kind),
  material: (path: string, name: string) =>
    call<string>("MaterialData", path, name),
  materialPaths: (path: string, files: string[]) =>
    call<string[]>("MaterialPaths", path, files),
  viewer: () => call<string>("PickViewer"),
  play: (d: Chart, m: number, all: boolean) => call<void>("Play", d, m, all),
  stop: () => call<void>("Stop"),
  quit: () => call<void>("Quit"),
  onClose: async (fn: () => void, pending: () => void = () => {}) => {
    if (!desktop) return () => {};
    const runtime = await rt();
    const close = runtime.Events.On("request-close", fn),
      busy = runtime.Events.On("operation-pending", pending);
    return () => {
      close();
      busy();
    };
  },
};
export interface AssetPlan {
  token: string;
  mode: string;
  changes: { from: string; to: string; hash: string }[];
  warnings: string[];
}
