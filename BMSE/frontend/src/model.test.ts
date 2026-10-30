import { describe, it, expect } from "vitest";
import {
  blank,
  newNote,
  changeMeasure,
  clipboardRead,
  clipboardWrite,
  cleanDefinitions,
  renumber,
  lanes,
  moveNotes,
  decode,
  quickTargets,
  swapDefinition,
} from "./model";

describe("editor document operations", () => {
  it("inserts and deletes measures without losing variable lengths", () => {
    const d = blank();
    d.measures[2] = 0.75;
    d.notes.push(newNote(d, 2.25, 73, 1, "normal", 12));
    const r = changeMeasure(d, 1, true);
    expect(r.notes[0].measure).toBe(3);
    expect(r.measures[3]).toBe(0.75);
    expect(changeMeasure(r, 1, false)).toEqual(d);
  });
  it("rejects insertion past measure 999", () => {
    const d = blank();
    d.notes.push({ ...newNote(d, 0, 37, 1, "normal", 16), measure: 999 });
    expect(() => changeMeasure(d, 0, true)).toThrow();
  });
  it("copies fractional positions through the original BMSE 3 clipboard", () => {
    const d = blank();
    d.base = 62;
    d.measures[0] = 0.75;
    d.notes.push(newNote(d, 0.25, 37, 3843, "long", 12));
    const text = clipboardWrite(d, new Set([d.notes[0].id]));
    const notes = clipboardRead(text, d, 0);
    expect(notes[0].position).toBeCloseTo(d.notes[0].position, 12);
    expect(notes[0].value).toBe(3843);
    expect(notes[0].kind).toBe("long");
  });
  it("keeps 2P 6/7 tracks distinct when moving", () => {
    const d = blank(),
      ls = lanes("DP", 7, "left", 8);
    d.notes.push(newNote(d, 0.25, 80, 1, "normal", 16));
    const r = moveNotes(d, new Set([d.notes[0].id]), 0, 1, ls, 16);
    expect(r.notes[0].channel).toBe(81);
  });
  it("reindexes resources and references together", () => {
    const d = blank();
    d.wav = { 2: "b.wav", 9: "a.wav" };
    d.notes.push(newNote(d, 0, 37, 9, "normal", 16));
    d.headers.LNOBJ = "09";
    const n = renumber(d, "wav", true);
    expect(n.notes[0].value).toBe(1);
    expect(n.wav[1]).toBe("a.wav");
    expect(n.headers.LNOBJ).toBe("01");
    expect(d.notes[0].value).toBe(9);
  });
  it("keeps LNOBJ and BGA source material when removing unused definitions", () => {
    const d = blank();
    d.wav = { 1: "a.wav", 2: "unused.wav", 9: "tail.wav" };
    d.bmp = { 2: "source.png" };
    d.bga = { 1: "02 0 0 256 256 0 0" };
    d.headers.LNOBJ = "09";
    d.notes.push(
      newNote(d, 0, 37, 1, "normal", 16),
      newNote(d, 0, 4, 1, "normal", 16),
    );
    const n = cleanDefinitions(d);
    expect(n.wav[2]).toBeUndefined();
    expect(n.wav[9]).toBe("tail.wav");
    expect(n.bmp[2]).toBe("source.png");
  });
  it("refuses renumbering opaque conditional definitions", () => {
    const d = blank();
    d.extra = ["#IF 1"];
    expect(() => renumber(d, "wav", false)).toThrow();
  });
  it("distinguishes lowercase IDs in base 62", () =>
    expect(decode("Az", 62)).not.toBe(decode("AZ", 62)));
  it("QuickSend takes the earliest leftmost note unless Shift selects all", () => {
    const d = blank();
    d.notes = [
      newNote(d, 0.5, 37, 1, "normal", 16),
      newNote(d, 0.25, 38, 1, "normal", 16),
      newNote(d, 0.25, 37, 1, "normal", 16),
    ];
    const ids = new Set(d.notes.map((n) => n.id));
    expect([...quickTargets(d, ids, false)]).toEqual([d.notes[2].id]);
    expect(quickTargets(d, ids, true).size).toBe(3);
  });
  it("swaps WAV references and LNOBJ together", () => {
    const d = blank();
    d.wav = { 1: "head.wav", 2: "tail.wav" };
    d.headers.LNOBJ = "02";
    d.notes = [newNote(d, 0, 37, 1, "normal", 16)];
    const n = swapDefinition(d, "wav", 1, 2);
    expect(n.notes[0].value).toBe(2);
    expect(n.headers.LNOBJ).toBe("01");
    expect(n.wav[2]).toBe("head.wav");
  });
  it("shifts unknown channel lines when inserting a measure", () => {
    const d = blank();
    d.extra = ["#IF 1", "#002ZZ:aa", "#ENDIF"];
    expect(changeMeasure(d, 1, true).extra[1]).toBe("#003ZZ:aa");
  });
});
