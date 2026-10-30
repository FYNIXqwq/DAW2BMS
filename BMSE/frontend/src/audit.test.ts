import { describe, it, expect } from "vitest";
import { statistics, longNotePairs } from "./statistics";
import { configuredBlank, initialSettings } from "./model";
import { normalizeSettings } from "./model";
import { translator } from "./legacy";
import {
  blank,
  atTime,
  newNote,
  moveNotes,
  lanes,
  resizeMeasures,
  changeBase,
  renumber,
  clipboardRead,
} from "./model";
import { findNotes, replaceValues, quickSend } from "./editing";

describe("original BMSE parity and regression audit", () => {
  it("rejects last-measure overflow without deleting any note", () => {
    const d = blank();
    d.notes = [
      { ...newNote(d, 0, 37, 1, "normal", 16), measure: 999, position: 0.75 },
    ];
    const before = structuredClone(d);
    expect(() => resizeMeasures(d, 999, 999, 0.5)).toThrow("999");
    expect(d).toEqual(before);
  });
  it("normalizes damaged configuration shapes and display bounds", () => {
    const s = normalizeSettings({
      ui: null,
      viewers: [null],
      selectedViewer: 999,
    });
    expect(s.ui).toEqual({});
    expect(s.selectedViewer).toBe(0);
    const unsafe = normalizeSettings({
      ui: { zoom: 999, grid: 0, laneZoom: -1 },
    });
    expect(unsafe.ui.zoom).toBe(3);
    expect(unsafe.ui.grid).toBe(16);
    expect(unsafe.ui.laneZoom).toBe(0.5);
  });
  it("keeps Chinese fallback captions when importing a custom Chinese language", () => {
    const t = translator(
      "chinese_simplified.ini",
      "[Main]\nKey=BMSE\n[Menu]\nFILE=我的文件",
    );
    expect(t("文件")).toBe("我的文件");
    expect(t("保存设置")).toBe("保存设置");
  });
  it("does not pair LNOBJ across an explicit long-note interval", () => {
    const d = blank();
    d.headers.LNOBJ = "ZZ";
    d.notes = [
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0.25, 37, 1, "long", 16),
      newNote(d, 0.5, 37, 1, "long", 16),
      newNote(d, 0.75, 37, 1295, "normal", 16),
    ];
    expect(longNotePairs(d)).toHaveLength(1);
  });
  it("counts LN and LNOBJ pairs once and merges PMS/OCT sides", () => {
    const d = blank();
    d.headers.LNOBJ = "ZZ";
    d.notes = [
      newNote(d, 0, 37, 1, "long", 16),
      newNote(d, 0.5, 37, 1, "long", 16),
      newNote(d, 0, 74, 1, "normal", 16),
      newNote(d, 0.5, 74, 1295, "normal", 16),
      newNote(d, 0.75, 74, 2, "mine", 16),
    ];
    const stats = statistics(d, "PMS");
    expect(stats.sides[0].long).toBe(2);
    expect(stats.sides[0].normal).toBe(0);
    expect(stats.total).toEqual([2, 0]);
    expect(longNotePairs(d)).toHaveLength(2);
  });
  it("honors imported new-document defaults", () => {
    const d = configuredBlank({
      ...initialSettings,
      ui: { defaultBase: 62, outputEncoding: "System" },
    });
    expect(d.base).toBe(62);
    expect(d.encoding).toBe("System");
  });
  it("keeps grids in absolute 192/grid ticks in variable measures", () => {
    const d = blank();
    d.measures[0] = 0.5;
    expect(atTime(d, 0.0625, 16).position).toBe(0.125);
    d.measures[0] = 2;
    expect(atTime(d, 0.0625, 16).position).toBe(0.03125);
  });
  it("horizontal movement preserves off-grid positions and fractions", () => {
    const d = blank();
    d.notes = [
      {
        ...newNote(d, 0, 37, 1, "normal", 16),
        position: 1 / 7,
        numerator: 1,
        denominator: 7,
      },
    ];
    const r = moveNotes(
      d,
      new Set([d.notes[0].id]),
      0,
      1,
      lanes("SP", 7, "left", 8),
      16,
    );
    expect(r.notes[0].position).toBe(1 / 7);
    expect(r.notes[0].denominator).toBe(7);
    expect(r.notes[0].channel).toBe(38);
  });
  it("moves a group without collapsing its relative timing at boundaries", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0.25, 38, 1, "normal", 16),
    ];
    const ids = new Set(d.notes.map((n) => n.id));
    expect(
      moveNotes(d, ids, -1 / 16, 0, lanes("SP", 7, "left", 8), 16),
    ).toEqual(d);
    const r = moveNotes(d, ids, 1 / 16, 0, lanes("SP", 7, "left", 8), 16);
    expect(r.notes[1].position - r.notes[0].position).toBe(0.25);
  });
  it("does not send hidden selected tracks into timing lanes", () => {
    const d = blank();
    d.notes = [newNote(d, 0.125, 73, 1, "normal", 16)];
    expect(
      moveNotes(
        d,
        new Set([d.notes[0].id]),
        0,
        1,
        lanes("SP", 7, "left", 8),
        16,
      ),
    ).toEqual(d);
  });
  it("shortening a measure carries overflow forward instead of scaling", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0.25, 37, 1, "normal", 16),
      newNote(d, 0.75, 38, 1, "normal", 16),
    ];
    const r = resizeMeasures(d, 0, 0, 0.5);
    expect(r.notes[0].measure).toBe(0);
    expect(r.notes[0].position).toBe(0.5);
    expect(r.notes[1].measure).toBe(1);
    expect(r.notes[1].position).toBe(0.25);
  });
  it("cannot repoint missing WAV or LNOBJ references during compaction", () => {
    const d = blank();
    d.wav[5] = "a.wav";
    d.notes = [
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0.25, 38, 5, "normal", 16),
    ];
    d.headers.LNOBJ = "02";
    const r = renumber(d, "wav", false);
    expect(r.notes[0].value).toBe(1);
    expect(r.headers.LNOBJ).toBe("02");
    expect(r.wav[1]).toBeUndefined();
    expect(r.wav[2]).toBeUndefined();
    expect(r.wav[3]).toBe("a.wav");
  });
  it("re-encodes BGA and LNOBJ on base change and rejects capacity loss", () => {
    const d = blank();
    d.bga[1] = "10 0 0 256 256 0 0";
    d.headers.LNOBJ = "10";
    const r = changeBase(d, 62);
    expect(r.headers.LNOBJ).toBe("0a");
    expect(r.bga[1]).toMatch(/^0a /);
    d.wav[300] = "outside.wav";
    expect(() => changeBase(d, 16)).toThrow();
  });
  it("protects SETRANDOM and unknown channels during reference rewriting", () => {
    for (const extra of ["#SETRANDOM 1", "#SETSWITCH 2", "#000ZZ:01"]) {
      const d = blank();
      d.extra = [extra];
      expect(() => renumber(d, "wav", false)).toThrow();
    }
  });
  it("finds ranges in selected objects across multiple tracks", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0, 38, 2, "normal", 16),
      newNote(d, 0, 39, 3, "normal", 16),
    ];
    const result = findNotes(
      d,
      {
        min: 0,
        max: 999,
        value: "01",
        valueTo: "03",
        channel: "37,38",
        kind: "",
        selectedOnly: true,
      },
      new Set([d.notes[1].id, d.notes[2].id]),
    );
    expect([...result]).toEqual([d.notes[1].id]);
  });
  it("replaces decimal BPM and zero SCROLL without treating them as material IDs", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0, 8, 130, "normal", 16),
      newNote(d, 0, 1020, 1, "normal", 16),
    ];
    expect(
      replaceValues(d, new Set([d.notes[0].id]), "150.25").notes[0].value,
    ).toBe(150.25);
    expect(replaceValues(d, new Set([d.notes[1].id]), "0").notes[1].value).toBe(
      0,
    );
    expect(() => replaceValues(d, new Set([d.notes[0].id]), "0")).toThrow();
  });
  it("Shift+Space preserves playable lane spacing in BGM", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0, 39, 2, "normal", 16),
    ];
    const r = quickSend(
      d,
      new Set(d.notes.map((n) => n.id)),
      "bgm",
      true,
      lanes("SP", 7, "left", 8),
    );
    expect(r.doc.notes[1].channel - r.doc.notes[0].channel).toBe(2);
    expect(r.selected.size).toBe(0);
  });
  it("rejects malformed clipboard records and negative xNT durations", () => {
    for (const text of [
      "BMSE other\nfoo",
      "iBMSC Clipboard Data xNT\n6 0 10000 -1 0 0",
      "iBMSC Clipboard Data\n6 -10 10000 0 0 0",
      "iBMSC Clipboard Data\n6 0 10001 0 0 0",
    ])
      expect(() => clipboardRead(text, blank(), 0, "standard")).toThrow();
  });
});
