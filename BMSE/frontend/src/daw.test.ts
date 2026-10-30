import { describe, it, expect } from "vitest";
import { dawLanguage, initialRoles, roleSelection } from "./daw";
import translations from "./daw-locales.json";

describe("DAW import selection", () => {
  const tracks = [
    { id: 7, name: "Lead", notes: 3, supported: true },
    { id: 8, name: "BGM", notes: 4, supported: true },
    { id: 9, name: "Unsupported", notes: 0, supported: false },
  ];
  it("defaults to BGM and never re-enables unsupported content", () => {
    expect(initialRoles(tracks)).toEqual({ 7: "bgm", 8: "bgm", 9: "exclude" });
    expect(roleSelection(tracks, { 7: "play", 8: "bgm", 9: "play" })).toEqual({
      playTracks: [7],
      excludeTracks: [9],
    });
  });
  it("keeps explicit BGM-only selection and stable source IDs", () => {
    expect(roleSelection(tracks, initialRoles(tracks)).playTracks).toEqual([]);
    expect(
      roleSelection(tracks, { 7: "exclude", 8: "play", 9: "exclude" }),
    ).toEqual({ playTracks: [8], excludeTracks: [7, 9] });
  });
  it("uses OS language unless explicitly overridden", () => {
    expect(dawLanguage("system", "zh-CN")).toBe("zh-TW");
    expect(dawLanguage("system", "ja-JP")).toBe("ja");
    expect(dawLanguage("en", "ko-KR")).toBe("en");
    expect(dawLanguage("system", "fr-FR")).toBe("en");
  });
  it("has matching translation keys and placeholders", () => {
    const english = translations.en;
    expect(translations['zh-TW']['Read tracks']).toBe('讀取音軌');
    for (const catalog of Object.values(translations)) {
      expect(Object.keys(catalog).sort()).toEqual(Object.keys(english).sort());
      for (const [key, value] of Object.entries(catalog))
        expect(value.match(/\{\w+\}/g)?.sort() ?? []).toEqual(
          (english as Record<string, string>)[key].match(/\{\w+\}/g)?.sort() ??
            [],
        );
    }
  });
});
