import { test, expect } from "@playwright/test";
import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";

test("disk apply cannot be dismissed; actual files and chart can be restored", async ({
  page,
}) => {
  const dir = mkdtempSync(path.resolve("../bin/assets-e2e-")),
    file = path.join(dir, "fixture.bms");
  writeFileSync(file, "#TITLE Disk test\n#BPM 130\n#WAV01 used.wav\n");
  writeFileSync(path.join(dir, "used.wav"), "used");
  writeFileSync(path.join(dir, "unused.wav"), "unused");
  await page.goto("http://127.0.0.1:9247/");
  await page.evaluate(async (file) => {
    const url = "/wails/runtime.js";
    const { Call } = await import(url);
    await Call.ByName("main.EditorService.Open", file, "Auto");
  }, file);
  await page.reload();
  await page.getByRole("button", { name: "文件(F)", exact: true }).click();
  await page.getByRole("menuitem", { name: file, exact: true }).click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Disk test",
  );
  await page.getByRole("button", { name: "工具(T)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "磁盘素材整理…", exact: true })
    .click();
  await page.getByRole("button", { name: "生成操作预览", exact: true }).click();
  await expect(page.locator(".asset-changes")).toContainText("unused.wav");
  let release = () => {};
  let intercepted = false;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/wails/runtime", async (route) => {
    const data = route.request().postDataJSON();
    if (data?.args?.methodName === "main.EditorService.ApplyAssets") {
      intercepted = true;
      await held;
    }
    await route.continue();
  });
  await page
    .getByRole("button", { name: "执行以上 1 项", exact: true })
    .click();
  await expect.poll(() => intercepted).toBe(true);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "磁盘素材整理", exact: true }),
  ).toBeVisible();
  await page.getByLabel("关闭对话框").click();
  await expect(
    page.getByRole("dialog", { name: "磁盘素材整理", exact: true }),
  ).toBeVisible();
  release();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(existsSync(path.join(dir, "unused.wav"))).toBe(false);
  expect(existsSync(path.join(dir, "used.wav"))).toBe(true);
  await page.getByRole("button", { name: "工具(T)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "磁盘素材整理…", exact: true })
    .click();
  await page
    .getByRole("button", { name: "恢复上次磁盘操作", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(existsSync(path.join(dir, "unused.wav"))).toBe(true);
});

test("invalid player parameter draft remains visible and blocks saving", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "播放器设置", exact: true }).click();
  await page.getByLabel("当前小节参数", { exact: true }).fill("not json");
  await expect(page).not.toHaveTitle(/\*$/);
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator(".inline-error")).toContainText("JSON");
  await expect(page.getByLabel("当前小节参数", { exact: true })).toHaveValue(
    "not json",
  );
  await page
    .getByLabel("当前小节参数", { exact: true })
    .fill('["-P","<filename>"]');
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "播放器设置", exact: true }).click();
  await expect(page.getByLabel("当前小节参数", { exact: true })).toHaveValue(
    '["-P","<filename>"]',
  );
});
