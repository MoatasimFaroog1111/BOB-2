import { expect, test } from "@playwright/test";

const API_ORIGIN = "http://127.0.0.1:8000";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("guardian_access_token", "e2e-access-token");
    sessionStorage.setItem("guardian_refresh_token", "e2e-refresh-token");
    sessionStorage.setItem("guardian_role", "owner");
  });

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/erp/chat-spreadsheet") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Set ANTHROPIC_API_KEY or start Ollama locally",
        }),
      });
      return;
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
});

test("documents workspace remains usable and hides provider configuration", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/documents");

  const grid = page.locator('[data-testid="spreadsheet-workspace"]');
  const assistant = page.getByRole("heading", { name: "مساعد التنسيق الذكي" });
  await expect(grid).toBeVisible();
  await expect(assistant).toBeVisible();

  const gridBox = await grid.boundingBox();
  expect(gridBox?.width).toBeGreaterThanOrEqual(480);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.locator("main [style]").count()).toBe(0);

  await page.getByPlaceholder("اكتب توجيهات التنسيق...").fill("نسق الجدول");
  await page.getByRole("button", { name: "أرسل" }).click();

  await expect(page.getByText("تعذر على الخدمة إكمال الطلب. حاول مرة أخرى.", { exact: false })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("ANTHROPIC");
  await expect(page.locator("body")).not.toContainText("API_KEY");
  await expect(page.locator("body")).not.toContainText("Ollama");
  const unexpectedConsoleErrors = consoleErrors.filter(
    (message) =>
      !message.includes("Failed to load resource") &&
      !message.includes("Applying inline style violates"),
  );
  expect(unexpectedConsoleErrors).toEqual([]);
});
