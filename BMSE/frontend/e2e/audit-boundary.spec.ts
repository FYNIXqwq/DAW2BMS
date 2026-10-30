import { test, expect } from "@playwright/test";
test("last-measure resize failure keeps notes and restores the displayed value", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "boundary.bms",
      mimeType: "text/plain",
      buffer: Buffer.from("#BPM 130\n#99911:00000001"),
    });
  await expect(page.locator(".statusbar")).toContainText("1 OBJ");
  await page.getByRole("tab", { name: "小节", exact: true }).click();
  await page.locator(".measure-list button").nth(999).click();
  await page.getByLabel("小节倍率", { exact: true }).fill("0.5");
  await page.getByLabel("小节倍率", { exact: true }).press("Tab");
  await expect(page.getByLabel("小节倍率", { exact: true })).toHaveValue("1");
  await expect(page.getByRole("alert")).toContainText("999");
  await expect(page.locator(".statusbar")).toContainText("1 OBJ");
  await expect(page.locator(".document-title")).not.toContainText("*");
});
