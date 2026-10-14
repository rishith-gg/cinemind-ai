import { expect, test } from "@playwright/test";

// The end-to-end data folder has no picture or text models (models are only ever fetched by
// `cinemind models pull`), so this checks the honest path in the real app: clips still process,
// scenes can still be edited by hand, and the clip page says why there are no tags.
test("scenes are editable by hand and the clip page explains missing tags", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Scenes ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();
  const card = page.getByRole("link", { name: "Open three_shots.mp4", exact: true });
  await expect(card).toContainText("Ready", { timeout: 120_000 });
  await expect(page.getByRole("link", { name: "Open prores_clip.mov" })).toContainText("Ready", { timeout: 120_000 });

  await page.getByRole("link", { name: "Shots / Scenes" }).click();
  await expect(page.getByRole("heading", { name: "Shots and scenes" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("so shots cannot be compared");
  const scenes = page.getByRole("article");
  await expect.poll(() => scenes.count(), { timeout: 30_000 }).toBeGreaterThan(2);
  const before = await scenes.count();
  await expect(page.getByText("Starts here: no picture vectors to compare").first()).toBeVisible();

  // Join the second scene to the first, then name it: both are kept by the server.
  await scenes.nth(1).getByRole("button", { name: "Join with the scene before" }).click();
  await expect(page.getByText("Joined with the scene before.")).toBeVisible();
  await expect(scenes).toHaveCount(before - 1);
  await expect(scenes.first().getByText("joined by you")).toBeVisible();
  const name = page.getByRole("textbox", { name: "Name of Scene 001" });
  await name.fill("Opening");
  await scenes.first().getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("article", { name: "Opening" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("article", { name: "Opening" })).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
  await card.click();
  const tags = page.getByRole("region", { name: "Tags" });
  await expect(tags.getByRole("note")).toContainText("uv run cinemind models pull");
});
