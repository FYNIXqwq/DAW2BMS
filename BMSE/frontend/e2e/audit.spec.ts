import { test, expect } from "@playwright/test";
import { readFileSync, mkdtempSync, writeFileSync } from "node:fs";
import path from "node:path";
import { blank, initialSettings } from "../src/model";

test("conditional save preserves source ordering and referenced event definitions", async ({
  page,
}) => {
  const source =
    "#TITLE Branch original\n#BPM01 150\n#RANDOM 2\n#IF 1\n#00008:01\n#ENDIF\n#ENDRANDOM\n#BPM01 175\n";
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "branch.bms",
      mimeType: "text/plain",
      buffer: Buffer.from(source),
    });
  await expect(page.getByLabel("标题", { exact: true })).toBeDisabled();
  await page.screenshot({ path: "../.impeccable/review/audit-source.png" });
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await expect(page.getByLabel("BMS 源码")).toHaveValue(source);
  const edited = source.replace("Branch original", "Branch edited");
  await page.getByLabel("BMS 源码").fill(edited);
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  const wait = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "保存 (Ctrl+S)", exact: true })
    .click();
  const dl = await wait;
  expect(readFileSync((await dl.path())!, "utf8")).toBe(edited);
});

test("applying untouched source does not create a new edit", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles(path.resolve("../samples/roundtrip.bms"));
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  await expect(page.locator(".document-title")).not.toContainText("*");
});

test("browser decoding handles UTF16 and downloads the selected GBK encoding", async ({
  page,
  request,
}) => {
  const raw = Buffer.concat([
    Buffer.from([255, 254]),
    Buffer.from("#TITLE 繁體測試\n#BPM 130", "utf16le"),
  ]);
  await page.goto("/");
  await page.locator("input[type=file]").first().setInputFiles({
    name: "unicode.bms",
    mimeType: "text/plain",
    buffer: raw,
  });
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "繁體測試",
  );
  await page.getByRole("button", { name: "选项(O)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "编码与编号…", exact: true })
    .click();
  await page.getByLabel("保存编码", { exact: true }).selectOption("GBK");
  await page.getByLabel("关闭对话框").click();
  const wait = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "保存 (Ctrl+S)", exact: true })
    .click();
  const file = await wait;
  const bytes = readFileSync((await file.path())!);
  const decoded = await request.post("/api/DecodeDocument", {
    data: [bytes.toString("base64"), "GBK"],
  });
  expect((await decoded.json()).headers.TITLE).toBe("繁體測試");
});

test("startup recovery survives defaults and cannot replace edits without confirmation", async ({
  page,
}) => {
  const recovery = blank();
  recovery.headers.TITLE = "Recovered chart";
  await page.addInitScript(
    (recovery) =>
      localStorage.setItem("bmse-recovery", JSON.stringify(recovery)),
    recovery,
  );
  await page.goto("/");
  await expect(page.locator(".recovery")).toContainText("Recovered chart");
  await page.getByLabel("标题", { exact: true }).fill("Current edits");
  await page.getByLabel("标题", { exact: true }).press("Tab");
  await page.waitForTimeout(900);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bmse-recovery")!).headers.TITLE,
    ),
  ).toBe("Recovered chart");
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "保存修改", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Current edits",
  );
});

test("a delayed clipboard cut cannot delete same-ID notes in another document", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: () =>
          new Promise<void>(
            (resolve) => ((window as any).releaseCut = resolve),
          ),
        readText: async () => "",
      },
    }),
  );
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "first.bms",
      mimeType: "text/plain",
      buffer: Buffer.from("#BPM 130\n#00011:01"),
    });
  await expect(page.locator('.statusbar')).toContainText('1 OBJ');
  await expect(page.locator('.busy-shield')).toHaveCount(0);
  await page.locator("canvas").focus();
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Control+x");
  await expect
    .poll(() => page.evaluate(() => typeof (window as any).releaseCut))
    .toBe("function");
  await page
    .getByRole("button", { name: "新建 (Ctrl+N)", exact: true })
    .click();
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await page.getByLabel("BMS 源码").fill("#BPM 130\n#00011:02");
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  await page.evaluate(() => (window as any).releaseCut());
  await expect(page.locator(".statusbar")).toContainText("1 OBJ");
  await expect(page.locator(".statusbar")).toContainText("未执行剪切");
});

test("pending view autosave cannot overwrite newly saved player profiles", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = window.setTimeout.bind(window),
      clear = window.clearTimeout.bind(window);
    let id = -1;
    const tasks = new Map<number, () => void>();
    window.setTimeout = ((fn: any, delay?: number, ...args: any[]) => {
      if (delay === 500) {
        const key = id--;
        tasks.set(key, () => fn(...args));
        return key;
      }
      return original(fn, delay, ...args);
    }) as typeof window.setTimeout;
    window.clearTimeout = (key?: number) => {
      if (key !== undefined && tasks.has(key)) tasks.delete(key);
      else clear(key);
    };
    (window as any).flushView = () => {
      for (const fn of tasks.values()) fn();
      tasks.clear();
    };
  });
  await page.goto("/");
  await page.getByLabel("高度缩放").selectOption("1.5");
  await page.getByRole("button", { name: "播放器设置", exact: true }).click();
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await page.evaluate(() => (window as any).flushView());
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bmse-settings")!).viewers.length,
    ),
  ).toBe(2);
});

test("extreme but valid measure lengths remain navigable through virtual scrolling", async ({
  page,
}) => {
  const source =
    "#BPM 130\n" +
    Array.from(
      { length: 1000 },
      (_, m) => `#${String(m).padStart(3, "0")}02:512`,
    ).join("\n") +
    "\n#99911:01";
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "large.bms",
      mimeType: "text/plain",
      buffer: Buffer.from(source),
    });
  await expect(page.locator(".statusbar")).toContainText("1 OBJ");
  await page.getByLabel("定位小节").fill("999");
  await page.getByLabel("定位小节").press("Tab");
  const canvas = await page.locator("canvas").boundingBox();
  if (!canvas) throw new Error("canvas missing");
  await page.mouse.move(canvas.x + 280, canvas.y + canvas.height - 50);
  await expect(page.locator(".statusbar")).toContainText("#999");
  expect(
    await page.locator(".chart-scroll").evaluate((el) => el.scrollHeight),
  ).toBeLessThanOrEqual(8_000_010);
});

test("native drop bridge keeps chart and imported media paths", async ({
  page,
}) => {
  const dir = mkdtempSync(path.resolve("../bin/drop-audit-")),
    file = path.join(dir, "drop.bms"),
    wav = path.join(dir, "sound.wav");
  writeFileSync(file, "#TITLE Dropped file\n#BPM 130");
  writeFileSync(wav, "fixture");
  let client = "";
  page.on("request", (r) => {
    if (r.url().endsWith("/wails/runtime"))
      client = r.headers()["x-wails-client-id"] || client;
  });
  await page.goto("http://127.0.0.1:9247/");
  await expect.poll(() => client).not.toBe("");
  await expect(page.locator(".busy-shield")).toHaveCount(0);
  const drop = async (file: string) => {
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
      { file, client },
    );
  };
  await drop(file);
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Dropped file",
  );
  await expect(page.locator(".busy-shield")).toHaveCount(0);
  await drop(wav);
  await expect(page.getByLabel("01", { exact: true })).toHaveValue("sound.wav");
  await page
    .getByRole("button", { name: "保存 (Ctrl+S)", exact: true })
    .click();
  await expect(page.locator(".statusbar")).toContainText("已保存");
  expect(readFileSync(file, "utf8")).toContain("#WAV01 sound.wav");
});

test("new defaults, WAV00 BMP00 and bulk measure length are accessible", async ({
  page,
}) => {
  await page.addInitScript(
    (s) => localStorage.setItem("bmse-settings", JSON.stringify(s)),
    {
      ...initialSettings,
      ui: { defaultBase: 62, outputEncoding: "UTF-8 BOM" },
    },
  );
  await page.goto("/");
  await page.getByRole("tab", { name: "扩展", exact: true }).first().click();
  await page.getByLabel("WAV00 地雷音").fill("mine.wav");
  await page.getByLabel("BMP00 MISS").fill("miss.png");
  await page.getByLabel("BMP00 MISS").press("Tab");
  await page.getByRole("tab", { name: "小节", exact: true }).click();
  await page.getByRole("button", { name: "批量长度…", exact: true }).click();
  await page.getByLabel("结束小节", { exact: true }).fill("2");
  await page.getByLabel("小节长度（倍数或分数）").fill("3/4");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "应用", exact: true })
    .click();
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  const text = await page.getByLabel("BMS 源码").inputValue();
  expect(text).toContain("#BASE 62");
  expect(text).toContain("#WAV00 mine.wav");
  expect(text).toContain("#BMP00 miss.png");
  expect(text).toContain("#00202:0.75");
});
