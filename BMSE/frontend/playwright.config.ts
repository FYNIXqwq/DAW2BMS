import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:9246",
    viewport: { width: 1280, height: 900 },
    launchOptions: {
      executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    },
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
