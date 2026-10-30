import { describe, it, expect } from "vitest";
import { blank, fingerprint } from "./model";
import { draftRows, assignDraft } from "./draft";

function fixture() {
  const d = blank();
  d.wav = { "1": "shared.wav" };
  d.dawDraft = {
    version: 1,
    sourceFile: "test.flp",
    sourceHash: "hash",
    daw: "fl_studio",
    ppq: 96,
    arrangementId: 0,
  };
  d.notes = [7, 8].map((trackId, i) => ({
    id: String(i),
    measure: 1,
    position: 1 / 7,
    numerator: 1,
    denominator: 7,
    channel: 1297 + i,
    kind: "normal" as const,
    value: 1,
    dawOrigin: {
      trackId,
      trackName: "Track",
      channelId: 10,
      instrumentName: "Piano",
      keyId: "same",
      pitch: 60,
      sourceIndex: i,
      originalTick: 0,
    },
  }));
  return d;
}
describe("DAW draft role assignment", () => {
  it("keeps shared WAV occurrences separate by source track", () => {
    const d = fixture(),
      before = fingerprint(d),
      rows = draftRows(d);
    expect(rows).toHaveLength(2);
    const moved = assignDraft(
      d,
      new Set(rows[0].notes.map((n) => n.id)),
      "play",
      [37],
    );
    expect(moved.notes[0]).toEqual({ ...d.notes[0], channel: 37 });
    expect(moved.notes[1]).toEqual(d.notes[1]);
    expect(fingerprint(d)).toBe(before);
    const back = assignDraft(moved, new Set(["0"]), "bgm", []);
    expect(back.notes).toEqual(d.notes);
  });
  it("rejects a batch rather than overwriting or dropping a simultaneous note", () => {
    const d = fixture(),
      before = fingerprint(d);
    expect(() => assignDraft(d, new Set(["0", "1"]), "play", [37])).toThrow(
      "Draft lane collision",
    );
    expect(fingerprint(d)).toBe(before);
  });
  it("protects LNOBJ starts and avoids the full long-note interval", () => {
    const d = fixture();
    d.headers.LNOBJ = "02";
    d.notes.push(
      {
        ...d.notes[0],
        id: "start",
        position: 0,
        numerator: 0,
        denominator: 1,
        channel: 37,
      },
      {
        ...d.notes[0],
        id: "end",
        position: 0.5,
        numerator: 1,
        denominator: 2,
        channel: 37,
        value: 2,
      },
    );
    expect(() => assignDraft(d, new Set(["start"]), "bgm", [])).toThrow(
      "Draft locked notes",
    );
    expect(() => assignDraft(d, new Set(["0"]), "play", [37])).toThrow(
      "Draft lane collision",
    );
    expect(
      assignDraft(d, new Set(["0"]), "play", [37, 38]).notes[0].channel,
    ).toBe(38);
  });
  it("never modifies sound, time or event count when distributing a chord", () => {
    const d = fixture();
    const got = assignDraft(d, new Set(["0", "1"]), "play", [37, 38]);
    expect(new Set(got.notes.map((n) => n.channel)).size).toBe(2);
    expect(got.notes.map(({ channel, ...n }) => n)).toEqual(
      d.notes.map(({ channel, ...n }) => n),
    );
  });
});
