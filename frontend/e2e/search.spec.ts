import { expect, test } from "@playwright/test";

// The end-to-end data folder has no picture or text models, so only the lists that need none
// (spoken words, labels) can answer; the page must still work and say nothing false. Also checks
// moving to the next clip from the clip page.
test("search finds shots by label, opens the moment, and the clip page moves to the next clip", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Search ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();
  const card = page.getByRole("link", { name: "Open three_shots.mp4", exact: true });
  await expect(card).toContainText("Ready", { timeout: 120_000 });

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Search" }).click();
  await page.getByLabel("Search shots").fill("three shots");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Search results" });
  await expect(results).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("status")).toContainText("Labels");
  const first = results.getByRole("listitem").first();
  await expect(first).toContainText("three_shots.mp4");
  await expect(first.getByRole("list", { name: "Why this result" })).toContainText("file: three_shots.mp4");
  await first.getByRole("link").click();
  await expect(page.getByRole("heading", { name: "three_shots.mp4" })).toBeVisible();

  // Previous / next without going back to the grid.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
  await page.getByLabel("Sort").selectOption("name");
  await page.getByRole("link", { name: /Open h264_clip\.mp4/ }).click();
  await expect(page.getByRole("heading", { name: "h264_clip.mp4" })).toBeVisible();
  await page.keyboard.press("n");
  await expect(page.getByRole("heading", { name: "prores_clip.mov" })).toBeVisible();
  await page.getByRole("link", { name: "Previous clip" }).click();
  await expect(page.getByRole("heading", { name: "h264_clip.mp4" })).toBeVisible();
});
