import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

test("real Wails service bridge parses, serializes and validates charts", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:9247/");
  await expect(page.locator(".error")).toHaveCount(0);
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("BMS 源码")
    .fill(readFileSync(path.resolve("../samples/roundtrip.bms"), "utf8"));
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "BMSE Rewrite Test Chart",
  );
  await expect(page.locator(".statusbar")).toContainText("59 OBJ");
  await page
    .getByRole("button", { name: "对象检查 (F11)", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("同音素材");
  await page.getByLabel("关闭对话框").click();
  await expect(page.locator(".error")).toHaveCount(0);
});
