import { expect, test } from "@playwright/test";

// The end-to-end data folder has no face models (models are only ever fetched by
// `cinemind models pull`), so this checks the honest "not downloaded" path in the real app:
// clips still process, and the Actors page and the clip page say what is missing and how to fix it.
test("actors without face models: clips still process and the UI says what to do", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Actors ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();
  const clip = page.getByRole("link", { name: "Open h264_clip.mp4" });
  await expect(clip).toContainText("Ready", { timeout: 120_000 });

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Actors" }).click();
  await expect(page.getByRole("heading", { name: "Actors" })).toBeVisible();
  await expect(page.getByText(/Groups can be wrong/)).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("The face models are not downloaded.");
  await expect(page.getByRole("alert")).toContainText("uv run cinemind models pull");
  await expect(page.getByRole("list", { name: "People" })).toHaveCount(0);

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
  await clip.click();
  const panel = page.getByRole("region", { name: "People" });
  await expect(panel.getByRole("alert")).toContainText("uv run cinemind models pull");
});
