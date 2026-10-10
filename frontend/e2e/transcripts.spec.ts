import { expect, test } from "@playwright/test";

// The end-to-end data folder has no speech model (models are only ever fetched by
// `cinemind models pull`), so this checks the honest "not downloaded" path in the real app:
// clips still process, and every transcript view says what is missing and how to fix it.
test("transcripts without a speech model: clips still process and the UI says what to do", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Transcripts ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();
  const clip = page.getByRole("link", { name: "Open h264_clip.mp4" });
  await expect(clip).toContainText(/Tech score \d+/, { timeout: 120_000 });
  await expect(clip).toContainText("Ready", { timeout: 120_000 });
  await expect(clip).not.toContainText("Speech ·");

  await page.getByRole("link", { name: "Transcripts" }).click();
  await expect(page.getByRole("alert")).toContainText("cinemind models pull");
  const row = page.getByRole("row", { name: /h264_clip\.mp4/ });
  await expect(row).toContainText("Speech model not downloaded");
  await page.getByLabel("Search transcripts").fill("hello");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(/No transcript contains “hello”/)).toBeVisible();
  await expect(page).toHaveURL(/\/transcripts\?q=hello$/);

  await row.getByRole("link", { name: "h264_clip.mp4" }).click();
  const panel = page.getByRole("region", { name: "Transcript" });
  await expect(panel.getByRole("note")).toContainText("is not downloaded");
  await expect(panel.getByRole("note")).toContainText("uv run cinemind models pull");
});
