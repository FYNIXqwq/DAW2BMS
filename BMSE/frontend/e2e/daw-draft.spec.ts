import { test, expect } from "@playwright/test";
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";

function fixture() {
  const root = mkdtempSync(path.resolve("../bin/draft-e2e-")),
    file = path.join(root, "draft.bme");
  const chart =
    "#TITLE DAW draft fixture\n#BPM 120\n#WAV01 shared.wav\n#WAV02 bass.wav\n#00101:01000200\n#00101:00010000\n#00101:01\n";
  writeFileSync(file, chart);
  const wav = Buffer.alloc(44 + 1600);
  wav.write("RIFF");
  wav.writeUInt32LE(wav.length - 8, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24);
  wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(1600, 40);
  for (const name of ["shared.wav", "bass.wav"])
    writeFileSync(path.join(root, name), wav);
  const events = [
    [7, 10, 384, "01", "piano"],
    [7, 11, 576, "02", "bass"],
    [7, 10, 480, "01", "piano"],
    [8, 10, 384, "01", "piano"],
  ].map(([track, channel, tick, wav, key], index) => ({
    source_index: index,
    bms_tick: tick,
    original_tick: Number(tick) - 384,
    bms_channel: "01",
    wav_id: wav,
    source_note: {
      track_id: track,
      track_name: track === 7 ? "Lead" : "Backing",
      channel_id: channel,
      channel_name: channel === 10 ? "Piano" : "Bass",
      instrument_name: channel === 10 ? "Piano" : "Bass",
      key_id: key,
      key: channel === 10 ? 60 : 36,
    },
  }));
  writeFileSync(
    path.join(root, "mapping.json"),
    JSON.stringify({
      schema_version: 2,
      chart_sha256: createHash("sha256").update(chart).digest("hex"),
      ppq: 96,
      source: { file: "fixture.flp", sha256: "a".repeat(64) },
      definitions: [
        { wav_id: "01", file: "shared.wav", key_id: "piano" },
        { wav_id: "02", file: "bass.wav", key_id: "bass" },
      ],
      events,
    }),
  );
  return { file, root, chart };
}

test("draft filters source occurrences, changes roles safely, and survives undo/save/reopen", async ({
  page,
}) => {
  const f = fixture();
  let client = "";
  page.on("request", (r) => {
    if (r.url().endsWith("/wails/runtime"))
      client = r.headers()["x-wails-client-id"] || client;
  });
  await page.goto("http://127.0.0.1:9247/");
  await page.evaluate(() => localStorage.setItem("bmse-daw-language", "en"));
  await expect.poll(() => client).not.toBe("");
  await page.evaluate(
    async ({ file, client }) => {
      await fetch("/wails/runtime", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-wails-client-id": client,
        },
        body: JSON.stringify({
          object: 3,
          method: 0,
          args: { name: "files-dropped", data: { files: [file] } },
        }),
      });
    },
    { file: f.file, client },
  );
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "DAW draft fixture",
  );
  async function openDraft() {
    await page.getByRole("button", { name: "文件(F)", exact: true }).click();
    await page
      .getByRole("menuitem", { name: "DAW 制作底稿…", exact: true })
      .click();
    return page.getByRole("dialog", { name: "DAW 制作底稿", exact: true });
  }
  const dialog = await openDraft();
  await expect(dialog.locator("tbody tr")).toHaveCount(3);
  await dialog.getByLabel("DAW track", { exact: true }).selectOption("7");
  await dialog
    .getByLabel("Instrument / channel", { exact: true })
    .selectOption("10");
  await expect(dialog.locator("tbody tr")).toHaveCount(1);
  await dialog
    .getByRole("button", { name: "Preview sound 01", exact: true })
    .click();
  await expect(dialog.getByLabel("Keysound preview")).toHaveAttribute(
    "src",
    /^data:/,
  );
  await dialog
    .getByRole("button", { name: "Select filtered", exact: true })
    .click();
  await dialog.getByLabel("Target keys", { exact: true }).selectOption("37");
  await dialog
    .getByRole("button", { name: "Move to keys", exact: true })
    .click();
  await expect(dialog.locator("tbody")).toContainText("2 keys / 0 BGM");
  await dialog.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(dialog.locator("tbody")).toContainText("0 keys / 2 BGM");
  await dialog.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(dialog.locator("tbody")).toContainText("2 keys / 0 BGM");
  await dialog.getByLabel("DAW track", { exact: true }).selectOption("8");
  await expect(
    dialog.getByRole("button", { name: "Move to keys", exact: true }),
  ).toBeDisabled();
  await dialog
    .getByRole("button", { name: "Select filtered", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Move to keys", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Nothing changed");
  await expect(dialog.locator("tbody")).toContainText("0 keys / 1 BGM");
  await dialog.getByLabel("DAW track", { exact: true }).selectOption("all");
  await dialog
    .getByRole("button", {
      name: "All editable draft notes to BGM",
      exact: true,
    })
    .click();
  await expect(dialog.locator("tbody tr").first()).toContainText(
    "0 keys / 2 BGM",
  );
  await dialog.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(dialog.locator("tbody tr").first()).toContainText(
    "2 keys / 0 BGM",
  );
  const shots = path.resolve("../.impeccable/review/draft");
  mkdirSync(shots, { recursive: true });
  for (const [lang, width, height] of [
    ["en", 1280, 900],
    ["zh-TW", 1024, 768],
    ["ja", 1024, 768],
    ["ko", 1024, 768],
  ] as const) {
    await page.setViewportSize({ width, height });
    await dialog.locator(".daw-intro select").selectOption(lang);
    await page.screenshot({ path: path.join(shots, lang + ".png") });
  }
  await dialog.locator(".daw-intro select").selectOption("en");
  await dialog.getByLabel("关闭对话框").click();
  await page
    .getByRole("button", { name: "保存 (Ctrl+S)", exact: true })
    .click();
  await expect
    .poll(() => readFileSync(f.file, "utf8"))
    .toContain("*BMSE_DAW1 ");
  const reopened = await page.evaluate(async (file) => {
    const url = "/wails/runtime.js";
    const { Call } = await import(url);
    return Call.ByName("main.EditorService.Open", file, "Auto");
  }, f.file);
  expect(reopened.notes).toHaveLength(4);
  expect(reopened.notes.filter((n: any) => n.channel === 37)).toHaveLength(2);
  expect(reopened.notes.every((n: any) => n.dawOrigin)).toBe(true);
  expect(
    reopened.notes.find((n: any) => n.dawOrigin.trackId === 8).channel,
  ).toBeGreaterThanOrEqual(1297);
  expect(
    reopened.notes
      .map((n: any) => `${n.measure}/${n.position}/${n.value}`)
      .sort(),
  ).toEqual(["1/0/1", "1/0/1", "1/0.25/1", "1/0.5/2"].sort());
  const reopenedDialog = await openDraft();
  await expect(reopenedDialog.locator("tbody tr")).toHaveCount(3);
});

test("changed source chart refuses stale mapping and remains editable", async ({
  page,
}) => {
  const f = fixture();
  writeFileSync(f.file, f.chart.replace("#001", " #002"));
  await page.goto("http://127.0.0.1:9247/");
  const result = await page.evaluate(async (file) => {
    const url = "/wails/runtime.js";
    const { Call } = await import(url);
    return Call.ByName("main.EditorService.Open", file, "Auto");
  }, f.file);
  expect(result.dawDraft).toBeUndefined();
  expect(result.notes).toHaveLength(4);
  expect(result.warnings.join("\n")).toContain("DAW_MAPPING_INVALID");
});
