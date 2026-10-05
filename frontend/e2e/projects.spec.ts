import { expect, test } from "@playwright/test";

test("create, open and delete a project in the real app", async ({ page }) => {
  const name = `E2E short film ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Projects" }).click();
  await expect(page.getByLabel("Project name")).toBeVisible();

  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const id = page.url().split("/").pop() ?? "";
  await expect(page.getByRole("combobox")).toHaveValue(id);

  // survives a reload (state comes from the backend) and re-selects the project
  await page.reload();
  await expect(page.getByRole("combobox")).toHaveValue(id);
  await expect(page.getByRole("heading", { name })).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Projects" }).click();
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: `Delete ${name}` }).click();
  await expect(page.getByRole("link", { name })).toHaveCount(0);
});

test("settings page shows the system check from the backend", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("backend-status")).toBeVisible({ timeout: 20_000 });
});
