import {
  copy,
  decode,
  eventChannel,
  keyChannel,
  quickTargets,
  starts,
} from "./model";
import type { Chart, Lane, Note } from "./model";

export interface FindQuery {
  min: number;
  max: number;
  value: string;
  valueTo?: string;
  channel: string;
  kind: string;
  selectedOnly?: boolean;
}
export function findNotes(
  d: Chart,
  q: FindQuery,
  selected: Set<string>,
): Set<string> {
  const channels = new Set(q.channel.split(",").filter(Boolean).map(Number));
  return new Set(
    d.notes
      .filter((n) => {
        if (
          n.measure < q.min ||
          n.measure > q.max ||
          (q.selectedOnly && !selected.has(n.id)) ||
          (channels.size && !channels.has(n.channel)) ||
          (q.kind && n.kind !== q.kind)
        )
          return false;
        if (!q.value && !q.valueTo) return true;
        const number = (s: string) =>
          eventChannel(n.channel)
            ? Number(s)
            : decode(s, n.kind === "mine" ? 36 : d.base);
        const low = q.value ? number(q.value) : -Infinity,
          high = q.valueTo ? number(q.valueTo) : q.value ? low : Infinity;
        return (
          !Number.isNaN(low) &&
          !Number.isNaN(high) &&
          n.value >= low &&
          n.value <= high
        );
      })
      .map((n) => n.id),
  );
}
export function replaceValues(d: Chart, ids: Set<string>, text: string): Chart {
  const result = copy(d);
  result.notes = result.notes.map((n) => {
    if (!ids.has(n.id)) return n;
    const isEvent = eventChannel(n.channel),
      base = n.kind === "mine" ? 36 : d.base,
      value = isEvent ? Number(text) : decode(text, base);
    if (
      !text.trim() ||
      !Number.isFinite(value) ||
      (isEvent && n.channel === 8 && value <= 0) ||
      (!isEvent &&
        (!Number.isInteger(value) || value < 1 || value >= base ** 2)) ||
      (!isEvent && !/^[0-9A-Za-z]{1,2}$/.test(text))
    )
      throw new Error("替换值不适用于匹配的对象类型");
    return { ...n, value };
  });
  return result;
}

export function quickSend(
  d: Chart,
  selected: Set<string>,
  channel: number | "bgm",
  all: boolean,
  lanes: Lane[],
): { doc: Chart; selected: Set<string> } {
  const targets = quickTargets(d, selected, all);
  if (!targets.size) return { doc: d, selected };
  const notes = d.notes.filter((n) => targets.has(n.id));
  const result = copy(d);
  const remaining = new Set([...selected].filter((id) => !targets.has(id)));
  if (channel === "bgm") {
    const a = starts(d),
      time = (n: Note) =>
        a[n.measure] + n.position * (d.measures[n.measure] || 1),
      times = notes.map(time);
    let min = Infinity,
      max = -Infinity;
    for (const t of times) {
      min = Math.min(min, t);
      max = Math.max(max, t);
    }
    const maxBGM = d.notes.reduce(
      (m, n) =>
        n.channel >= 1297 && time(n) >= min - 1e-10 && time(n) <= max + 1e-10
          ? Math.max(m, n.channel)
          : m,
      1296,
    );
    const playable = lanes.filter((l) => keyChannel(l.channel));
    if (all) {
      if (maxBGM + playable.length > 1424)
        throw new Error("没有足够的 BGM 空轨道");
      if (
        notes.some(
          (n) =>
            keyChannel(n.channel) &&
            !playable.some((l) => l.channel === n.channel),
        )
      )
        throw new Error("请先显示所选对象的全部轨道");
      result.notes = result.notes
        .filter(
          (n) => !targets.has(n.id) || !["mine", "invisible"].includes(n.kind),
        )
        .map((n) =>
          targets.has(n.id) && keyChannel(n.channel)
            ? {
                ...n,
                channel:
                  maxBGM +
                  1 +
                  playable.findIndex((l) => l.channel === n.channel),
                kind: "normal",
              }
            : n,
        );
    } else {
      if (notes[0].channel < 1297 && maxBGM >= 1424)
        throw new Error("BGM 轨道已满");
      result.notes = result.notes.map((n) =>
        targets.has(n.id) && n.channel < 1297
          ? { ...n, channel: maxBGM + 1, kind: "normal" }
          : n,
      );
    }
  } else {
    if (!lanes.some((l) => l.channel === channel)) return { doc: d, selected };
    const occupied = new Set(
      d.notes
        .filter((n) => !targets.has(n.id) && n.channel === channel)
        .map((n) => `${n.measure}/${n.position.toFixed(10)}/${n.kind}`),
    );
    for (const n of notes) {
      const key = `${n.measure}/${n.position.toFixed(10)}/${n.kind}`;
      if (occupied.has(key)) throw new Error("目标轨道已有对象");
      occupied.add(key);
    }
    result.notes = result.notes.map((n) =>
      targets.has(n.id) ? { ...n, channel } : n,
    );
  }
  return { doc: result, selected: remaining };
}
