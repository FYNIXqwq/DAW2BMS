import { test, expect } from "@playwright/test";
import path from "node:path";
async function preferences(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "选项(O)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "主题 / 语言 / 快捷键…", exact: true })
    .click();
}
test("OCT layout, legacy configuration, languages and multiple viewers", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("谱面模式").selectOption("OCT");
  await expect(page.getByLabel("谱面模式")).toHaveValue("OCT");
  await preferences(page);
  await page.getByLabel("主题方案").selectOption("default_oct.ini");
  const themeText = await page.getByLabel("主题 INI").inputValue();
  await page
    .getByLabel("主题 INI")
    .fill(themeText.replace(/^Name=.*$/m, 'Name="Custom audit"'));
  await page.getByRole("tab", { name: "快捷键", exact: true }).click();
  const text = await page.getByLabel("快捷键 INI").inputValue();
  await page.getByLabel("快捷键 INI").fill(text.replace("FOOT=Q", "FOOT=R"));
  await page.getByRole("tab", { name: "播放器", exact: true }).click();
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await page.getByLabel("名称", { exact: true }).fill("Second player");
  await page.getByLabel("名称", { exact: true }).press("Tab");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await preferences(page);
  await expect(
    page.locator('select[aria-label="主题方案"] option:checked'),
  ).toHaveText("Custom audit");
  await page.getByRole("tab", { name: "播放器", exact: true }).click();
  await expect(page.getByLabel("播放器列表")).toHaveValue("1");
  await expect(page.getByLabel("名称", { exact: true })).toHaveValue(
    "Second player",
  );
  await page.screenshot({ path: "../.impeccable/review/preferences.png" });
  await page.getByRole("tab", { name: "语言", exact: true }).click();
  await page.getByLabel("界面语言").selectOption("english.ini");
  await page
    .getByRole("button", { name: "Save settings", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "File(F)", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Options(O)", exact: true }).click();
  await page
    .getByRole("menuitem", {
      name: "Theme / Language / Shortcuts…",
      exact: true,
    })
    .click();
  await page.getByRole("tab", { name: "Language", exact: true }).click();
  await page
    .getByLabel("Interface language")
    .selectOption("chinese_simplified.ini");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  await expect(page.getByLabel("BMS 源码")).toContainText("#OCT/FP 1");
  await page.getByLabel("关闭对话框").click();
  await page.screenshot({ path: "../.impeccable/review/oct-desktop.png" });
  expect(errors).toEqual([]);
});

test("BGA crop editor draws correct source and target pixels", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "BMP", exact: true }).click();
  const png = await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 256;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "red";
    ctx.fillRect(0, 0, 128, 256);
    ctx.fillStyle = "blue";
    ctx.fillRect(128, 0, 128, 256);
    return c.toDataURL().split(",")[1];
  });
  await page
    .locator("input[type=file]")
    .nth(1)
    .setInputFiles({
      name: "crop-test.png",
      mimeType: "image/png",
      buffer: Buffer.from(png, "base64"),
    });
  await page.getByRole("tab", { name: "BGA", exact: true }).click();
  await page.getByTitle("添加素材", { exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "BGA 裁剪与偏移", exact: true }),
  ).toBeVisible();
  await page.getByLabel("x1", { exact: true }).fill("128");
  await page.getByLabel("x1", { exact: true }).press("Tab");
  await expect
    .poll(() =>
      page
        .getByLabel("BGA 目标位置")
        .evaluate((el: HTMLCanvasElement) =>
          Array.from(el.getContext("2d")!.getImageData(10, 10, 1, 1).data),
        ),
    )
    .toEqual([0, 0, 255, 255]);
  await page.screenshot({ path: "../.impeccable/review/bga-editor.png" });
  await page
    .getByRole("dialog", { name: "BGA 裁剪与偏移", exact: true })
    .getByRole("button", { name: "应用", exact: true })
    .click();
  await expect(page.getByLabel("01", { exact: true })).toHaveValue(
    "01 128 0 256 256 0 0",
  );
});

test("conditional branches open as a separate chart and Tips remains usable", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "conditional.bms",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "#BPM 130\n#RANDOM 2\n#IF 1\n#00011:01\n#ELSE\n#00012:02\n#ENDIF\n#ENDRANDOM",
      ),
    });
  await page.getByRole("button", { name: "工具(T)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "展开随机 / 条件分支…", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.locator("dialog input[type=number]").fill("2");
  await page.getByRole("button", { name: "生成独立谱面", exact: true }).click();
  await expect(page.locator(".statusbar")).toContainText("1 OBJ");
  await page.getByRole("button", { name: "BMS 文本…", exact: true }).click();
  const source = await page.getByLabel("BMS 源码").inputValue();
  expect(source).toContain("#00012:02");
  expect(source).not.toContain("#RANDOM");
  await page.getByLabel("关闭对话框").click();
  await page.getByRole("button", { name: "帮助(H)", exact: true }).click();
  await page.getByRole("menuitem", { name: "Tips", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Tips", exact: true }),
  ).toBeVisible();
  const first = await page.locator(".tip-text").innerText();
  await page.getByRole("button", { name: "下一条", exact: true }).click();
  expect(await page.locator(".tip-text").innerText()).not.toBe(first);
});
