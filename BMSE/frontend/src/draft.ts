import { copy, decode, keyChannel } from "./model";
import type { Chart, Note } from "./model";

const time = (n: Note) => n.measure + n.position;
const at = (n: Note) => `${n.measure}/${n.position.toFixed(12)}`;
export interface DraftRow {
  id: string;
  trackId: number;
  trackName: string;
  channelId: number;
  instrumentName: string;
  pitch: number;
  value: number;
  notes: Note[];
  playable: number;
  bgm: number;
  locked: number;
}

function longNotes(d: Chart) {
  const spans: { channel: number; start: number; end: number }[] = [],
    locked = new Set<string>();
  const byChannel = new Map<number, Note[]>();
  for (const n of d.notes)
    if (keyChannel(n.channel)) {
      const notes = byChannel.get(n.channel) || [];
      notes.push(n);
      byChannel.set(n.channel, notes);
    }
  const lnobj = decode(d.headers.LNOBJ || "00", d.base);
  for (const [channel, notes] of byChannel) {
    notes.sort((a, b) => time(a) - time(b));
    let start: Note | undefined, previous: Note | undefined;
    for (const n of notes) {
      if (n.kind === "long") {
        locked.add(n.id);
        if (start) {
          spans.push({ channel, start: time(start), end: time(n) });
          start = undefined;
        } else start = n;
      }
      if (n.kind === "normal") {
        if (lnobj > 0 && n.value === lnobj) {
          locked.add(n.id);
          if (previous) {
            locked.add(previous.id);
            spans.push({ channel, start: time(previous), end: time(n) });
          }
          previous = undefined;
        } else previous = n;
      }
    }
    if (start) spans.push({ channel, start: time(start), end: Infinity });
  }
  return { spans, locked };
}

export function draftRows(d: Chart): DraftRow[] {
  const rows = new Map<string, DraftRow>(),
    { locked } = longNotes(d);
  for (const n of d.notes) {
    const s = n.dawOrigin;
    if (!s) continue;
    const id = JSON.stringify([s.trackId, s.channelId, s.keyId, n.value]);
    let row = rows.get(id);
    if (!row) {
      row = {
        id,
        trackId: s.trackId,
        trackName: s.trackName,
        channelId: s.channelId,
        instrumentName: s.instrumentName,
        pitch: s.pitch,
        value: n.value,
        notes: [],
        playable: 0,
        bgm: 0,
        locked: 0,
      };
      rows.set(id, row);
    }
    row.notes.push(n);
    if (
      n.kind !== "normal" ||
      locked.has(n.id) ||
      (!keyChannel(n.channel) && n.channel < 1297)
    )
      row.locked++;
    else if (n.channel >= 1297) row.bgm++;
    else row.playable++;
  }
  return [...rows.values()].sort(
    (a, b) =>
      a.trackId - b.trackId ||
      a.channelId - b.channelId ||
      a.pitch - b.pitch ||
      a.value - b.value,
  );
}

export function editableDraftIDs(d: Chart): Set<string> {
  const { locked } = longNotes(d);
  return new Set(
    d.notes
      .filter(
        (n) =>
          n.dawOrigin &&
          n.kind === "normal" &&
          !locked.has(n.id) &&
          (keyChannel(n.channel) || n.channel >= 1297),
      )
      .map((n) => n.id),
  );
}

// Transactional: compute all destinations first. Never change event time, sound,
// count, source identity or unrelated notes, and never silently drop an overflow.
export function assignDraft(
  d: Chart,
  ids: Set<string>,
  target: "bgm" | "play",
  lanes: number[],
): Chart {
  if (d.sourceText) throw new Error("Draft protected chart");
  const { spans, locked } = longNotes(d),
    notes = d.notes.filter((n) => ids.has(n.id));
  if (!notes.length) return d;
  if (
    notes.some((n) => !n.dawOrigin || n.kind !== "normal" || locked.has(n.id))
  )
    throw new Error("Draft locked notes");
  const candidates =
    target === "bgm"
      ? Array.from({ length: 128 }, (_, i) => 1297 + i)
      : [...new Set(lanes)].filter(keyChannel);
  if (!candidates.length) throw new Error("Draft no lanes");
  const occupied = new Set(
    d.notes.filter((n) => !ids.has(n.id)).map((n) => `${at(n)}/${n.channel}`),
  );
  const byLane = new Map<number, { start: number; end: number }[]>();
  for (const span of spans) {
    const list = byLane.get(span.channel) || [];
    list.push(span);
    byLane.set(span.channel, list);
  }
  for (const [channel, list] of byLane) {
    list.sort((a, b) => a.start - b.start);
    const merged: { start: number; end: number }[] = [];
    for (const span of list) {
      const last = merged[merged.length - 1];
      if (last && span.start <= last.end)
        last.end = Math.max(last.end, span.end);
      else merged.push({ ...span });
    }
    byLane.set(channel, merged);
  }
  const inLong = (channel: number, t: number) => {
    const list = byLane.get(channel) || [];
    let low = 0,
      high = list.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (list[mid].start <= t) low = mid + 1;
      else high = mid;
    }
    return low > 0 && list[low - 1].end >= t;
  };
  const assigned = new Map<string, number>(),
    last = new Map<number, number>();
  for (const n of [...notes].sort(
    (a, b) =>
      time(a) - time(b) ||
      a.dawOrigin!.sourceIndex - b.dawOrigin!.sourceIndex ||
      a.id.localeCompare(b.id),
  )) {
    const available = candidates.filter(
      (c) => !occupied.has(`${at(n)}/${c}`) && !inLong(c, time(n)),
    );
    if (!available.length) throw new Error("Draft lane collision");
    const channel = available.includes(n.channel)
      ? n.channel
      : target === "bgm"
        ? available[0]
        : available.sort(
            (a, b) =>
              (last.get(a) ?? -Infinity) - (last.get(b) ?? -Infinity) || a - b,
          )[0];
    assigned.set(n.id, channel);
    last.set(channel, time(n));
    occupied.add(`${at(n)}/${channel}`);
  }
  const result = copy(d);
  for (const n of result.notes)
    if (assigned.has(n.id)) n.channel = assigned.get(n.id)!;
  return result;
}
