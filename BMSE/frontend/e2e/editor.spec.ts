import { test, expect } from "@playwright/test";
import path from "node:path";

test("edit, undo, search, variable measures, source roundtrip and unsaved guard", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator(".busy-shield")).toHaveCount(0);
  await page.keyboard.press("Alt+f");
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles(path.resolve("../samples/roundtrip.bms"));
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  await page.getByLabel("标题", { exact: true }).fill("Cancelled title");
  await page.getByLabel("标题", { exact: true }).press("Escape");
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  await page.getByLabel("BPM", { exact: true }).fill("999");
  await page.getByLabel("BPM", { exact: true }).press("Escape");
  await expect(page.getByLabel("BPM", { exact: true })).toHaveValue("130");
  await page.getByLabel("标题", { exact: true }).fill("Still focused draft");
  await page.getByLabel("标题", { exact: true }).press("Control+n");
  await expect(
    page.getByRole("dialog", { name: "保存修改", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page
    .getByRole("button", { name: "撤销 (Ctrl+Z)", exact: true })
    .click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  const before = await page.locator(".statusbar").innerText();
  expect(before).toContain("OBJ");
  await page.screenshot({ path: "../.impeccable/review/desktop.png" });
  await page.getByLabel("标题", { exact: true }).fill("Changed title");
  await page.getByLabel("标题", { exact: true }).press("Tab");
  await page
    .getByRole("button", { name: "撤销 (Ctrl+Z)", exact: true })
    .click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  await page
    .getByRole("button", { name: "重做 (Ctrl+Y)", exact: true })
    .click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Changed title",
  );
  await page
    .getByRole("button", { name: "查找替换 (Ctrl+F)", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "查找 / 替换", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../.impeccable/review/audit-find.png" });
  await page.getByLabel("编号 / 数值", { exact: true }).fill("01");
  await page.getByLabel("编号 / 数值", { exact: true }).press("Tab");
  await page.getByRole("button", { name: "选中", exact: true }).click();
  await expect(page.locator(".chart-tools")).toContainText("选中");
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  const beforeBrowsing = await page.getByLabel("BMS 源码").inputValue();
  await page.getByLabel("关闭对话框").click();
  await page.getByRole("listbox", { name: "WAV 素材列表" }).focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  expect(await page.getByLabel("BMS 源码").inputValue()).toBe(beforeBrowsing);
  await page.getByLabel("关闭对话框").click();
  await page.locator("canvas").focus();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Control+z");
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await expect(page.getByLabel("BMS 源码")).toContainText(
    "#CUSTOM migration-fixture-preserved",
  );
  const source = await page.getByLabel("BMS 源码").inputValue();
  expect(source).toContain("#00102:0.75");
  await page
    .getByLabel("BMS 源码")
    .fill(source.replace("#TITLE Changed title", "#TITLE Source edit"));
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Source edit",
  );
  await page
    .getByRole("button", { name: "新建 (Ctrl+N)", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("未保存");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Source edit",
  );
  await page.getByRole("button", { name: "写入 (F3)", exact: true }).click();
  const box = await page.locator("canvas").boundingBox();
  if (!box) throw new Error("canvas missing");
  await page.mouse.click(
    box.x + 48 + 44 * 4 + 43 + 6 * 38 + 19,
    box.y + box.height - 95,
  );
  await expect(page.locator(".statusbar")).toContainText("60 OBJ");
  await page
    .getByRole("button", { name: "对象检查 (F11)", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("关闭对话框").click();
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.screenshot({ path: "../.impeccable/review/desktop-1024.png" });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
