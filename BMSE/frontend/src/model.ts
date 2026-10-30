export type Kind = "normal" | "invisible" | "long" | "mine";
export interface Note {
  dawOrigin?: DawOrigin;
  id: string;
  measure: number;
  position: number;
  numerator: number;
  denominator: number;
  channel: number;
  kind: Kind;
  value: number;
}
export interface Chart {
  dawDraft?: {version:number;sourceFile:string;sourceHash:string;daw:string;ppq:number;arrangementId:number};
  editorMode?: string;
  path: string;
  encoding: string;
  base: number;
  headers: Record<string, string>;
  wav: Record<string, string>;
  bmp: Record<string, string>;
  bga: Record<string, string>;
  measures: Record<number, number>;
  notes: Note[];
  extra: string[];
  warnings: string[];
  definitions?: Record<number, Record<number, number>>;
  sourceText?: string;
  sourceHash?: string;
}
export interface DawOrigin {
  trackId:number;trackName:string;channelId:number;instrumentName:string;
  keyId:string;pitch:number;sourceIndex:number;originalTick:number;
}
export interface Issue {
  severity: string;
  message: string;
  noteId: string;
  measure: number;
}
export interface Viewer {
  name: string;
  path: string;
  playArgs: string[];
  allArgs: string[];
  stopArgs: string[];
}
export interface Settings {
  recent: string[];
  viewer: string;
  playArgs: string[];
  allArgs: string[];
  stopArgs: string[];
  ui: Record<string, unknown>;
  viewers?: Viewer[];
  selectedViewer?: number;
}
export type Mode = "select" | "write" | "delete";
export type Material = "wav" | "bmp" | "bga";
export const initialSettings: Settings = {
  recent: [],
  viewer: "",
  playArgs: ["-P", "-N<measure>", "<filename>"],
  allArgs: ["-P", "-N0", "<filename>"],
  stopArgs: ["-S"],
  ui: {},
};
export function normalizeSettings(value: unknown): Settings {
  const raw =
    value && typeof value === "object" ? (value as Partial<Settings>) : {};
  const args = (v: unknown, fallback: string[]) =>
    Array.isArray(v) && v.every((x) => typeof x === "string") ? v : fallback;
  const profiles = Array.isArray(raw.viewers)
    ? raw.viewers
        .filter((v) => v && typeof v === "object")
        .map((p) => ({
          name: typeof p.name === "string" ? p.name : "Player",
          path: typeof p.path === "string" ? p.path : "",
          playArgs: args(p.playArgs, ["<filename>"]),
          allArgs: args(p.allArgs, ["<filename>"]),
          stopArgs: args(p.stopArgs, []),
        }))
    : undefined;
  const ui =
    raw.ui && typeof raw.ui === "object" && !Array.isArray(raw.ui)
      ? { ...raw.ui }
      : {};
  if (typeof ui.zoom === "number")
    ui.zoom = Math.min(
      3,
      Math.max(0.25, Number.isFinite(ui.zoom) ? ui.zoom : 1),
    );
  if (typeof ui.laneZoom === "number")
    ui.laneZoom = Math.min(
      3,
      Math.max(0.5, Number.isFinite(ui.laneZoom) ? ui.laneZoom : 1),
    );
  if (
    typeof ui.grid === "number" &&
    (!Number.isInteger(ui.grid) || ui.grid < 1 || ui.grid > 192)
  )
    ui.grid = 16;
  return {
    recent: args(raw.recent, []).slice(0, 10),
    viewer: typeof raw.viewer === "string" ? raw.viewer : "",
    playArgs: args(raw.playArgs, initialSettings.playArgs),
    allArgs: args(raw.allArgs, initialSettings.allArgs),
    stopArgs: args(raw.stopArgs, initialSettings.stopArgs),
    ui,
    viewers: profiles,
    selectedViewer: Math.max(
      0,
      Math.min(
        (profiles?.length || 1) - 1,
        Number.isInteger(raw.selectedViewer) ? raw.selectedViewer! : 0,
      ),
    ),
  };
}
export const blank = (): Chart => ({
  path: "",
  encoding: "UTF-8",
  base: 36,
  headers: {
    PLAYER: "1",
    TITLE: "",
    ARTIST: "",
    GENRE: "",
    BPM: "130",
    PLAYLEVEL: "1",
    RANK: "2",
  },
  wav: {},
  bmp: {},
  bga: {},
  measures: {},
  notes: [],
  extra: [],
  warnings: [],
});
export function configuredBlank(settings: Settings) {
  const d = blank(),
    base = Number(settings.ui.defaultBase),
    encoding = String(settings.ui.outputEncoding || "UTF-8");
  if ([16, 36, 62].includes(base)) d.base = base;
  if (
    [
      "System",
      "UTF-8",
      "UTF-8 BOM",
      "Shift-JIS",
      "EUC-KR",
      "GBK",
      "Big5",
      "UTF-16LE",
      "UTF-16BE",
      "UTF-32LE",
      "UTF-32BE",
    ].includes(encoding)
  )
    d.encoding = encoding;
  return d;
}
export const uid = () => crypto.randomUUID();
export const copy = <T>(v: T): T => structuredClone(v);
export const fingerprint = (d: Chart) =>
  JSON.stringify({ ...d, path: "", warnings: [] });
export const keyChannel = (c: number) =>
  (c >= 37 && c <= 45) || (c >= 73 && c <= 81);
export const eventChannel = (c: number) => [8, 9, 1020, 1033].includes(c);
const digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
export const encode = (n: number, base = 36) =>
  n >= 0 && n < base * base
    ? digits[Math.floor(n / base)] + digits[n % base]
    : "??";
export function decode(s: string, base = 36) {
  let v = 0;
  for (const c of base === 62 ? s : s.toUpperCase()) {
    const d = digits.indexOf(c);
    if (d < 0 || d >= base) return NaN;
    v = v * base + d;
  }
  return v;
}
export const pad = (n: number) => String(n).padStart(3, "0");
export function playerMode(d: Chart): string {
  const mode = d.editorMode;
  if (d.headers["OCT/FP"] !== undefined) return "OCT";
  if (mode === "PMS" && ["1", "3"].includes(d.headers.PLAYER)) return "PMS";
  if (
    (mode === "SP" && d.headers.PLAYER === "1") ||
    (mode === "2P" && d.headers.PLAYER === "2") ||
    (mode === "DP" && d.headers.PLAYER === "3")
  )
    return mode;
  if (d.path.toLowerCase().endsWith(".pms")) return "PMS";
  return d.headers.PLAYER === "2"
    ? "2P"
    : d.headers.PLAYER === "3"
      ? "DP"
      : "SP";
}
export function starts(d: Chart) {
  const a = [0];
  for (let m = 0; m <= 999; m++) a.push(a[m] + (d.measures[m] || 1));
  return a;
}
export function atTime(d: Chart, t: number, grid: number) {
  const a = starts(d);
  t = Math.max(0, Math.min(a[1000] - 1e-9, t));
  let m = 0;
  while (m < 999 && a[m + 1] <= t) m++;
  const ratio = d.measures[m] || 1;
  // Original BMSE grids use 192/grid ticks regardless of the measure ratio.
  const offset = Math.floor(Math.max(0, t - a[m]) * grid + 1e-9) / grid;
  const pos = Math.min(1 - 1e-12, offset / ratio);
  return {
    measure: m,
    position: pos,
    numerator: 0,
    denominator: 0,
  };
}

export function positionAtTime(d: Chart, t: number) {
  const a = starts(d);
  if (!Number.isFinite(t) || t < 0 || t >= a[1000])
    throw new Error("位置超出 000–999 小节");
  let lo = 0,
    hi = 999;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    if (a[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return {
    measure: lo,
    position: (t - a[lo]) / (d.measures[lo] || 1),
    numerator: 0,
    denominator: 0,
  };
}

export function hasOpaqueReferences(d: Chart) {
  return (
    !!d.sourceText ||
    d.extra.some((l) =>
      /^\s*#(?:RANDOM|RONDAM|SETRANDOM|SWITCH|SETSWITCH|IF|ELSE|CASE|DEF|WAV|BMP|BGA|\d{3}[0-9A-Za-z]{2}:)/i.test(
        l,
      ),
    )
  );
}

export function changeBase(d: Chart, base: number): Chart {
  if (![16, 36, 62].includes(base)) throw new Error("不支持的进制");
  if (base === d.base) return d;
  if (hasOpaqueReferences(d))
    throw new Error("未解析指令或条件分支存在，不能安全转换进制");
  const limit = base * base;
  for (const table of [
    d.wav,
    d.bmp,
    d.bga,
    ...Object.values(d.definitions || {}),
  ])
    for (const [id, value] of Object.entries(table)) {
      if (value !== "" && +id >= limit)
        throw new Error("现有编号超出目标进制容量");
    }
  for (const n of d.notes)
    if (!eventChannel(n.channel) && n.kind !== "mine" && n.value >= limit)
      throw new Error("对象编号超出目标进制容量");
  const next = copy(d);
  if (next.headers.LNOBJ) {
    const id = decode(next.headers.LNOBJ, d.base);
    if (!Number.isInteger(id) || id < 1 || id >= limit)
      throw new Error("LNOBJ 超出目标进制容量");
    next.headers.LNOBJ = encode(id, base);
  }
  for (const [id, value] of Object.entries(next.bga)) {
    if (!value.trim()) continue;
    const parts = value.trim().split(/\s+/),
      source = decode(parts[0], d.base);
    if (!Number.isInteger(source) || source < 0 || source >= limit)
      throw new Error("BGA 源编号超出目标进制容量");
    parts[0] = encode(source, base);
    next.bga[id] = parts.join(" ");
  }
  next.base = base;
  return next;
}

export function resizeMeasures(
  d: Chart,
  first: number,
  last: number,
  ratio: number,
): Chart {
  if (
    !Number.isInteger(first) ||
    !Number.isInteger(last) ||
    first < 0 ||
    last > 999 ||
    first > last ||
    !Number.isFinite(ratio) ||
    ratio <= 0 ||
    ratio > 512
  )
    throw new Error("无效的小节范围或倍率");
  if (hasOpaqueReferences(d))
    throw new Error("含未解析指令的小节长度请在 BMS 文本中修改");
  const next = copy(d);
  for (let m = first; m <= last; m++) next.measures[m] = ratio;
  next.notes = next.notes.flatMap((n) => {
    if (n.measure < first || n.measure > last) return [n];
    let m = n.measure,
      offset = n.position * (d.measures[m] || 1);
    while (m <= 999 && offset >= (next.measures[m] || 1) - 1e-12) {
      offset -= next.measures[m] || 1;
      m++;
    }
    if (m > 999) throw new Error("修改会使音符超过第 999 小节，谱面未更改");
    return [
      {
        ...n,
        measure: m,
        position: Math.max(0, offset) / (next.measures[m] || 1),
        numerator: 0,
        denominator: 0,
      },
    ];
  });
  return next;
}
export function newNote(
  d: Chart,
  t: number,
  channel: number,
  value: number,
  kind: Kind,
  grid: number,
): Note {
  return {
    ...atTime(d, t, grid),
    channel,
    value,
    kind: keyChannel(channel) ? kind : "normal",
    id: uid(),
  };
}

export interface Lane {
  channel: number;
  label: string;
  bg: string;
  color: string;
  width: number;
}
export function lanes(
  player: string,
  keys: number,
  scratch: string,
  bgm: number,
  scratch2?: string,
): Lane[] {
  const result: Lane[] = [1033, 1020, 8, 9].map((channel, i) => ({
    channel,
    label: ["SP", "SC", "BPM", "STOP"][i],
    bg: "#303000",
    color: "#d8d830",
    width: 44,
  }));
  const key = (channel: number, label: string, sc = false): Lane => ({
    channel,
    label,
    bg: sc ? "#300000" : (channel % 36) % 2 === 0 ? "#000028" : "#202020",
    color: sc ? "#ff6868" : (channel % 36) % 2 === 0 ? "#7373ff" : "#d0d0d0",
    width: sc ? 43 : 38,
  });
  if (player === "OCT") {
    result.push(key(73, "FOOT", true), key(42, "LSC", true));
    [37, 38, 39, 40, 41, 44, 45, 74, 75, 76, 77, 80, 81].forEach((c, i) =>
      result.push(key(c, String(i + 1))),
    );
    result.push(key(78, "RSC", true));
  } else if (player === "PMS") {
    [37, 38, 39, 40, 41, 74, 75, 76, 77].forEach((c, i) =>
      result.push({
        ...key(c, String(i + 1)),
        color: [
          "#eee",
          "#efb74a",
          "#67ce63",
          "#7373ff",
          "#ff6868",
          "#7373ff",
          "#67ce63",
          "#efb74a",
          "#eee",
        ][i],
      }),
    );
  } else {
    const addSide = (side: number) => {
      const sc = key(side * 36 + 6, side === 1 ? "SC" : "2SC", true);
      const position =
        side === 1
          ? scratch
          : scratch2 || (scratch === "left" ? "right" : "left");
      if (position === "left") result.push(sc);
      [1, 2, 3, 4, 5, ...(keys === 7 ? [8, 9] : [])].forEach((n, i) =>
        result.push(
          key(side * 36 + n, side === 1 ? String(i + 1) : `2-${i + 1}`),
        ),
      );
      if (position === "right") result.push(sc);
    };
    addSide(1);
    if (player === "DP" || player === "2P") addSide(2);
  }
  [4, 7, 6].forEach((channel, i) =>
    result.push({
      channel,
      label: ["BGA", "LAYER", "POOR"][i],
      bg: "#002828",
      color: "#57d3d3",
      width: 46,
    }),
  );
  for (let i = 0; i < bgm; i++)
    result.push({
      channel: 1297 + i,
      label: `B${i + 1}`,
      bg: "#102410",
      color: "#65d765",
      width: 40,
    });
  return result;
}

export function changeMeasure(d: Chart, m: number, insert: boolean): Chart {
  const next = copy(d);
  if (
    insert &&
    (d.notes.some((n) => n.measure === 999) ||
      d.measures[999] ||
      d.extra.some((l) => /^#999[0-9a-z]{2}:/i.test(l.trim())))
  )
    throw new Error("第 999 小节已有数据，不能继续插入。");
  next.notes = next.notes
    .filter((n) => insert || n.measure !== m)
    .map((n) =>
      n.measure >= m ? { ...n, measure: n.measure + (insert ? 1 : -1) } : n,
    );
  next.measures = {};
  for (const [key, ratio] of Object.entries(d.measures)) {
    const k = Number(key);
    if (!insert && k === m) continue;
    next.measures[k >= m ? k + (insert ? 1 : -1) : k] = ratio;
  }
  next.extra = d.extra.flatMap((line) => {
    const match = /^(\s*#)(\d{3})([0-9a-z]{2}:.*)$/i.exec(line);
    if (!match || +match[2] < m) return [line];
    if (!insert && +match[2] === m) return [];
    return [match[1] + pad(+match[2] + (insert ? 1 : -1)) + match[3]];
  });
  return next;
}

export function quickTargets(
  d: Chart,
  selected: Set<string>,
  all: boolean,
): Set<string> {
  const sorted = d.notes
    .filter(
      (n) => selected.has(n.id) && (keyChannel(n.channel) || n.channel >= 1297),
    )
    .sort(
      (a, b) =>
        a.measure - b.measure ||
        a.position - b.position ||
        a.channel - b.channel,
    );
  return new Set((all ? sorted : sorted.slice(0, 1)).map((n) => n.id));
}

export function swapDefinition(
  d: Chart,
  table: Material,
  a: number,
  b: number,
): Chart {
  if (hasOpaqueReferences(d)) throw new Error("条件分支中的引用不能安全交换。");
  const n = copy(d),
    exchange = (v: number) => (v === a ? b : v === b ? a : v);
  if (table === "wav") {
    [n.wav[a], n.wav[b]] = [n.wav[b] || "", n.wav[a] || ""];
    n.notes.forEach((note) => {
      if (
        (keyChannel(note.channel) && note.kind !== "mine") ||
        note.channel >= 1297
      )
        note.value = exchange(note.value);
    });
    if (n.headers.LNOBJ)
      n.headers.LNOBJ = encode(
        exchange(decode(n.headers.LNOBJ, n.base)),
        n.base,
      );
  } else {
    for (const t of ["bmp", "bga"] as const)
      [n[t][a], n[t][b]] = [n[t][b] || "", n[t][a] || ""];
    n.notes.forEach((note) => {
      if ([4, 6, 7].includes(note.channel)) note.value = exchange(note.value);
    });
    for (const [k, v] of Object.entries(n.bga)) {
      if (!v) continue;
      const parts = v.split(/\s+/);
      parts[0] = encode(exchange(decode(parts[0], n.base)), n.base);
      n.bga[k] = parts.join(" ");
    }
  }
  return n;
}
export function moveNotes(
  d: Chart,
  ids: Set<string>,
  delta: number,
  laneDelta: number,
  ls: Lane[],
  grid: number,
  anchorID?: string,
): Chart {
  const selected = d.notes.filter((n) => ids.has(n.id));
  if (!selected.length || !Number.isFinite(delta)) return d;
  const a = starts(d),
    time = (n: Note) =>
      a[n.measure] + n.position * (d.measures[n.measure] || 1);
  if (anchorID && Math.abs(delta) > 1e-10) {
    const anchor = selected.find((n) => n.id === anchorID) || selected[0],
      target = time(anchor) + delta;
    if (target < 0 || target >= a[1000]) return d;
    const snapped = atTime(d, target, grid);
    delta =
      a[snapped.measure] +
      snapped.position * (d.measures[snapped.measure] || 1) -
      time(anchor);
  }
  const indices = new Map(ls.map((l, i) => [l.channel, i]));
  if (
    selected.some(
      (n) =>
        time(n) + delta < 0 ||
        time(n) + delta >= a[1000] ||
        (laneDelta !== 0 &&
          (!indices.has(n.channel) ||
            indices.get(n.channel)! + laneDelta < 0 ||
            indices.get(n.channel)! + laneDelta >= ls.length)),
    )
  )
    return d;
  const next = copy(d);
  next.notes = next.notes.map((n) => {
    if (!ids.has(n.id)) return n;
    const channel =
      laneDelta === 0
        ? n.channel
        : ls[indices.get(n.channel)! + laneDelta].channel;
    return {
      ...n,
      ...(Math.abs(delta) < 1e-12 ? {} : positionAtTime(d, time(n) + delta)),
      channel,
      kind: keyChannel(channel) ? n.kind : "normal",
    };
  });
  return next;
}
export function cleanDefinitions(d: Chart): Chart {
  if (hasOpaqueReferences(d))
    throw new Error("存在条件分支或未解析素材引用，不能安全清理定义。");
  const n = copy(d),
    waves = new Set<number>([0]),
    images = new Set<number>([0]);
  const ln = decode(d.headers.LNOBJ || "00", d.base);
  if (ln) waves.add(ln);
  d.notes.forEach((x) => {
    if ([4, 6, 7].includes(x.channel)) images.add(x.value);
    else if ((keyChannel(x.channel) && x.kind !== "mine") || x.channel >= 1297)
      waves.add(x.value);
  });
  const usedBga = new Set(images);
  for (const id of usedBga) {
    const bga = d.bga[id];
    if (bga) images.add(decode(bga.split(/\s+/)[0], d.base));
  }
  for (const k of Object.keys(n.wav)) if (!waves.has(+k)) delete n.wav[k];
  for (const k of Object.keys(n.bmp)) if (!images.has(+k)) delete n.bmp[k];
  for (const k of Object.keys(n.bga)) if (!usedBga.has(+k)) delete n.bga[k];
  return n;
}
export function renumber(d: Chart, table: Material, byName: boolean): Chart {
  if (hasOpaqueReferences(d))
    throw new Error("存在条件分支或未解析素材定义，不能安全重排编号。");
  if (table === "bga")
    throw new Error("BGA 与 BMP 共用编号，请在 BMP 列表整理。");
  const n = copy(d),
    ids = [
      ...new Set([
        ...Object.keys(n[table]),
        ...(table === "bmp" ? Object.keys(n.bga) : []),
      ]),
    ]
      .filter((k) => +k > 0 && (n[table][k] || (table === "bmp" && n.bga[k])))
      .sort((a, b) =>
        byName
          ? (n[table][a] || n.bga[a] || "").localeCompare(
              n[table][b] || n.bga[b] || "",
            )
          : +a - +b,
      );
  const defined = new Set(ids.map(Number)),
    reserved = new Set<number>();
  const reserve = (id: number) => {
    if (Number.isInteger(id) && id > 0 && !defined.has(id)) reserved.add(id);
  };
  for (const note of d.notes)
    if (
      table === "wav"
        ? (keyChannel(note.channel) && note.kind !== "mine") ||
          note.channel >= 1297
        : [4, 6, 7].includes(note.channel)
    )
      reserve(note.value);
  if (table === "wav") reserve(decode(d.headers.LNOBJ || "00", d.base));
  else
    for (const recipe of Object.values(d.bga))
      if (recipe.trim()) reserve(decode(recipe.trim().split(/\s+/)[0], d.base));
  const map = new Map<number, number>();
  let nextID = 1;
  for (const id of ids) {
    while (reserved.has(nextID)) nextID++;
    if (nextID >= d.base ** 2) throw new Error("没有足够的安全编号");
    map.set(+id, nextID++);
  }
  n[table] = n[table][0] ? { 0: n[table][0] } : {};
  ids.forEach((id) => {
    if (d[table][id]) n[table][map.get(+id)!] = d[table][id];
  });
  n.notes = n.notes.map((x) =>
    ((table === "wav" &&
      ((keyChannel(x.channel) && x.kind !== "mine") || x.channel >= 1297)) ||
      (table === "bmp" && [4, 6, 7].includes(x.channel))) &&
    map.has(x.value)
      ? { ...x, value: map.get(x.value)! }
      : x,
  );
  if (table === "wav" && n.headers.LNOBJ) {
    const old = decode(n.headers.LNOBJ, d.base);
    if (map.has(old)) n.headers.LNOBJ = encode(map.get(old)!, d.base);
  }
  if (table === "bmp") {
    const bga: Record<string, string> = {};
    for (const [k, v] of Object.entries(d.bga)) {
      const parts = v.split(/\s+/),
        source = decode(parts[0], d.base);
      if (map.has(source)) parts[0] = encode(map.get(source)!, d.base);
      bga[map.get(+k) ?? +k] = parts.join(" ");
    }
    n.bga = bga;
  }
  return n;
}

export function clipboardWrite(d: Chart, selected: Set<string>): string {
  const notes = d.notes.filter((n) => selected.has(n.id));
  if (!notes.length) return "";
  const origin = notes.reduce((min, n) => Math.min(min, n.measure), 999),
    a = starts(d);
  const doubleHex = (v: number) => {
    const view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, v);
    return view.getBigUint64(0).toString(16).padStart(16, "0").toUpperCase();
  };
  return (
    "BMSE3.0 ClipBoard Object Data Format\r\n" +
    notes
      .map(
        (n) =>
          n.channel.toString(36).toUpperCase().padStart(3, "0") +
          ["normal", "invisible", "long", "mine"].indexOf(n.kind) +
          doubleHex(
            (a[n.measure] -
              a[origin] +
              n.position * (d.measures[n.measure] || 1)) *
              192,
          ) +
          n.value,
      )
      .join("\r\n") +
    "\r\n"
  );
}
export function clipboardRead(
  text: string,
  d: Chart,
  measure: number,
  variant = "extended",
  scratch = "left",
): Note[] {
  if (text.length > 32 * 1024 * 1024) throw new Error("剪贴板数据过大");
  const lines = text.trim().split(/\r?\n/),
    first = lines.shift(),
    a = starts(d);
  const hexDouble = (s: string) => {
    const view = new DataView(new ArrayBuffer(8));
    view.setBigUint64(0, BigInt("0x" + s));
    return view.getFloat64(0);
  };
  if (
    ![
      "BMSE ClipBoard Object Data Format",
      "BMSE3.0 ClipBoard Object Data Format",
      "iBMSC Clipboard Data",
      "iBMSC Clipboard Data xNT",
    ].includes(first || "")
  )
    throw new Error("剪贴板不是 BMSE / iBMSC 对象数据。");
  const result: Note[] = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    let channel: number,
      time: number,
      value: number,
      kind: Kind = "normal",
      tail = 0;
    if (first!.startsWith("iBMSC")) {
      const p = line.trim().split(/\s+/).map(Number);
      channel =
        (
          {
            2: 8,
            3: 9,
            1: 1020,
            5: 42,
            7: 37,
            8: 38,
            9: 39,
            10: 40,
            11: 41,
            12: 44,
            13: 45,
            32: 73,
            33: 74,
            34: 75,
            35: 76,
            36: 77,
            37: 80,
            38: 81,
            57: 78,
            59: 4,
            60: 7,
            61: 6,
          } as Record<number, number>
        )[p[0]] ?? (p[0] >= 63 ? 1297 + p[0] - 63 : 0);
      if (variant === "standard") {
        channel =
          (
            {
              1: 1020,
              2: 8,
              3: 9,
              5: 42,
              6: 37,
              7: 38,
              8: 39,
              9: 40,
              10: 41,
              11: 44,
              12: 45,
              14: 73,
              15: 74,
              16: 75,
              17: 76,
              18: 77,
              19: 80,
              20: 81,
              21: 78,
              23: 4,
              24: 7,
              25: 6,
            } as Record<number, number>
          )[p[0]] ?? (p[0] >= 27 ? 1297 + p[0] - 27 : 0);
      }
      if (scratch === "right" && p[0] >= 5 && p[0] <= 12) {
        channel = [37, 38, 39, 40, 41, 44, 45, 42][p[0] - 5];
      }
      if (scratch === "right" && variant === "extended" && p[0] === 13)
        channel = 0;
      if (p.length !== 6 || p.some((v) => !Number.isFinite(v)))
        throw new Error("iBMSC 剪贴板必须包含六列有效数值");
      time = p[1] / 192;
      value = p[2] / 10000;
      kind = p[4] ? "invisible" : p[5] ? "mine" : p[3] ? "long" : "normal";
      if (first!.endsWith("xNT") && p[3] < 0)
        throw new Error("xNT 长度不能为负数");
      if (first!.endsWith("xNT") && p[3] > 0 && !p[4] && !p[5]) {
        kind = "long";
        tail = p[3] / 192;
      }
    } else {
      channel = parseInt(line.slice(0, 3), 36);
      kind = (["normal", "invisible", "long", "mine"] as Kind[])[+line[3]];
      const modern = first!.startsWith("BMSE3.0");
      if (
        !/^[0-9A-Z]{3}[0-3]/.test(line) ||
        (modern && !/^[0-9a-f]{16}$/i.test(line.slice(4, 20))) ||
        line.slice(modern ? 20 : 11).trim() === ""
      )
        throw new Error("BMSE 剪贴板字段无效");
      time =
        (modern ? hexDouble(line.slice(4, 20)) : Number(line.slice(4, 11))) /
        192;
      value = Number(line.slice(modern ? 20 : 11));
    }
    if (
      !channel ||
      !Number.isFinite(time) ||
      time < 0 ||
      !Number.isFinite(value) ||
      !kind ||
      channel > 1424
    )
      throw new Error("剪贴板包含无效对象。");
    if (
      !keyChannel(channel) &&
      !eventChannel(channel) &&
      ![4, 6, 7].includes(channel) &&
      channel < 1297
    )
      throw new Error("剪贴板轨道无效");
    if (
      !eventChannel(channel) &&
      (!Number.isInteger(value) ||
        value < 1 ||
        value >= (kind === "mine" ? 36 : d.base) ** 2)
    )
      throw new Error("剪贴板素材编号无效");
    const add = (t: number) => {
      if (result.length >= 200000) throw new Error("剪贴板对象过多");
      const abs = a[measure] + t;
      if (abs >= a[1000] || abs < 0) throw new Error("粘贴超出小节范围。");
      let m = measure;
      while (m < 999 && a[m + 1] <= abs) m++;
      result.push({
        id: uid(),
        measure: m,
        position: (abs - a[m]) / (d.measures[m] || 1),
        numerator: 0,
        denominator: 0,
        channel,
        kind,
        value,
      });
    };
    add(time);
    if (tail) add(time + tail);
  }
  return result;
}
