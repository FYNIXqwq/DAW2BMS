import { test, expect } from "@playwright/test";
test("undo and redo restore the chart layout including DP versus PMS", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("谱面模式").selectOption("DP");
  await page.getByLabel("谱面模式").selectOption("PMS");
  await page
    .getByRole("button", { name: "撤销 (Ctrl+Z)", exact: true })
    .click();
  await expect(page.getByLabel("谱面模式")).toHaveValue("DP");
  await page
    .getByRole("button", { name: "重做 (Ctrl+Y)", exact: true })
    .click();
  await expect(page.getByLabel("谱面模式")).toHaveValue("PMS");
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  const source = await page.getByLabel("BMS 源码").inputValue();
  await page.getByLabel("BMS 源码").fill(source + "\n#TITLE Mode remains PMS");
  await page.getByRole("button", { name: "应用到谱面", exact: true }).click();
  await expect(page.getByLabel("谱面模式")).toHaveValue("PMS");
});
