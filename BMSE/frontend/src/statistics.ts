import { decode, keyChannel } from "./model";
import type { Chart, Note, Kind } from "./model";
export function longNotePairs(d: Chart): [Note, Note][] {
  const pairs: [Note, Note][] = [],
    normal = new Map<number, Note>(),
    long = new Map<number, Note>(),
    marker = decode(d.headers.LNOBJ || "00", d.base);
  const time = (n: Note) => n.measure + n.position;
  for (const n of [...d.notes].sort((a, b) => time(a) - time(b))) {
    if (!keyChannel(n.channel)) continue;
    if (n.kind === "long") {
      normal.delete(n.channel);
      const head = long.get(n.channel);
      if (head) {
        if (time(n) > time(head)) pairs.push([head, n]);
        long.delete(n.channel);
      } else long.set(n.channel, n);
    } else if (n.kind === "normal") {
      if (marker && n.value === marker) {
        const head = normal.get(n.channel);
        if (head && !long.has(n.channel) && time(n) > time(head))
          pairs.push([head, n]);
        normal.delete(n.channel);
      } else if (!long.has(n.channel)) normal.set(n.channel, n);
    }
  }
  return pairs;
}
export function statistics(d: Chart, player: string) {
  const sides: [Record<Kind, number>, Record<Kind, number>] = [
      { normal: 0, invisible: 0, long: 0, mine: 0 },
      { normal: 0, invisible: 0, long: 0, mine: 0 },
    ],
    pairs = longNotePairs(d),
    paired = new Set(pairs.flatMap((pair) => pair.map((n) => n.id)));
  const side = (n: Note) =>
    ["PMS", "OCT"].includes(player) || n.channel < 73 ? 0 : 1;
  for (const [head] of pairs) sides[side(head)].long++;
  let unpaired = 0;
  for (const n of d.notes) {
    if (!keyChannel(n.channel) || paired.has(n.id)) continue;
    if (n.kind === "long") {
      unpaired++;
      continue;
    }
    sides[side(n)][n.kind]++;
  }
  return {
    sides,
    total: sides.map((s) => s.normal + s.long),
    unpaired,
    bgm: d.notes.filter((n) => n.channel >= 1297).length,
  };
}
