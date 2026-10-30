import { describe, it, expect } from "vitest";
import {
  parseIni,
  shortcutMap,
  defaultShortcuts,
  validateShortcuts,
  importViewers,
  importLegacy,
  themes,
  languages,
  translator,
  laneTheme,
} from "./legacy";
import { parseBGA, formatBGA, drawBGA } from "./BGAEditor";
import { blank, clipboardRead, lanes } from "./model";
import { initialSettings } from "./model";
describe("legacy feature compatibility", () => {
  it("imports a complete bmse.ini bundle", () => {
    const s = importLegacy(
      {
        "bmse.ini":
          "[Main]\nKey=BMSE\nTheme=custom.ini\nLanguage=english.ini\n[View]\nHeight=150\nSC_2P=0\n[Options]\nBaseNumber=62",
        "theme/custom.ini": "[Main]\nKey=BMSE\nBackground=1,2,3",
      },
      initialSettings,
    );
    expect(s.ui.zoom).toBe(1.5);
    expect(s.ui.scratch2).toBe("left");
    expect(s.ui.defaultBase).toBe(62);
    expect(s.ui.themeText).toContain("1,2,3");
  });
  it("does not mutate prototypes when reading an INI", () => {
    const ini = parseIni("[__proto__]\npolluted=yes");
    expect(({} as Record<string, string>).polluted).toBeUndefined();
    expect(ini.__proto__.polluted).toBe("yes");
  });
  it("supports independent scratch positions and two-player layouts", () => {
    const ls = lanes("2P", 7, "left", 1, "left");
    expect(ls.filter((l) => l.channel >= 37 && l.channel <= 81)).toHaveLength(
      16,
    );
    expect(ls.findIndex((l) => l.channel === 78)).toBeLessThan(
      ls.findIndex((l) => l.channel === 73),
    );
  });
  it("loads original themes and all bundled languages", () => {
    expect(Object.keys(languages)).toHaveLength(4);
    const theme = parseIni(themes["default_oct.ini"]);
    expect(theme.Main.Key).toBe("BMSE");
    expect(laneTheme(lanes("OCT", 7, "left", 8)[0], theme).bg).toMatch(/rgb/);
    expect(translator("english.ini")("保存")).toBe("Save");
    expect(translator("japanese.ini")("取消")).toBe("キャンセル");
  });
  it("maps original OCT keyboard and custom INI", () => {
    const map = shortcutMap(defaultShortcuts, "OCT");
    expect(map.KeyQ).toBe(73);
    expect(map.KeyM).toBe(81);
    expect(map.KeyK).toBe(78);
    expect(
      shortcutMap(defaultShortcuts.replace("SC=A", "SC=R"), "SP").KeyR,
    ).toBe(42);
    expect(() => validateShortcuts("[SP]\nKEY1=A\nKEY2=A")).toThrow();
  });
  it("renders all 13 OCT keys, two scratches and foot once", () => {
    const ls = lanes("OCT", 7, "left", 8).filter(
      (l) => l.channel >= 37 && l.channel <= 81,
    );
    expect(ls).toHaveLength(16);
    expect(new Set(ls.map((l) => l.channel)).size).toBe(16);
  });
  it("imports quoted legacy multi-viewer arguments", () => {
    const players = importViewers(
      'uBMplay\nC:\\Player Folder\\play.exe\n-P "<filename>"\n-P -N<measure> "<filename>"\n-S\n\nOther\nother.exe\n<filename>\n<filename>\n\n',
    );
    expect(players).toHaveLength(2);
    expect(players[0].playArgs).toEqual(["-P", "-N<measure>", "<filename>"]);
  });
  it("roundtrips BGA crop and clamps rendering size to 256", () => {
    const b = parseBGA("0a 10 20 500 400 30 40", 62);
    expect(formatBGA(b, 62)).toBe("0a 10 20 500 400 30 40");
    const calls: unknown[][] = [];
    const ctx = {
      fillStyle: "",
      fillRect: () => {},
      drawImage: (...a: unknown[]) => calls.push(a),
    };
    drawBGA(
      ctx as unknown as CanvasRenderingContext2D,
      {} as CanvasImageSource,
      b,
    );
    expect(calls[0].slice(1)).toEqual([10, 20, 256, 256, 30, 40, 256, 256]);
    expect(() => formatBGA({ ...b, x2: 0 }, 62)).toThrow();
  });
  it("reads xNT duration from its actual fourth field", () => {
    const n = clipboardRead(
      "iBMSC Clipboard Data xNT\n6 48 10000 96 0 0",
      blank(),
      0,
      "standard",
    );
    expect(n).toHaveLength(2);
    expect(n[0].channel).toBe(37);
    expect(n[0].position).toBe(0.25);
    expect(n[1].position).toBe(0.75);
  });
  it("distinguishes legacy and expanded column layouts", () => {
    expect(
      clipboardRead(
        "iBMSC Clipboard Data\n27 0 10000 0 0 0",
        blank(),
        0,
        "standard",
      )[0].channel,
    ).toBe(1297);
    expect(
      clipboardRead(
        "iBMSC Clipboard Data\n63 0 10000 0 0 0",
        blank(),
        0,
        "extended",
      )[0].channel,
    ).toBe(1297);
  });
});
