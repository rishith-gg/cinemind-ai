import { expect, test } from "@playwright/test";

test("technical quality: scores and QC flags in the library and on the clip, with reasons", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Quality ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();

  // The blurred clip with a silent gap is flagged for exactly those two things; the clean clip is not.
  const soft = page.getByRole("link", { name: "Open soft_quiet.mp4" });
  await expect(soft).toContainText("Soft picture", { timeout: 120_000 });
  await expect(soft).toContainText("Long silence");
  const clean = page.getByRole("link", { name: "Open h264_clip.mp4" });
  await expect(clean).toContainText(/Tech score \d+/, { timeout: 120_000 });
  await expect(clean).not.toContainText("Soft picture");
  const score = async (card: typeof soft) => Number(/Tech score (\d+)/.exec((await card.textContent()) ?? "")?.[1]);
  expect(await score(soft)).toBeLessThan(await score(clean));

  // Filter the library down to flagged clips.
  await expect(page.getByRole("link", { name: "Open three_shots.mp4" })).toContainText(/Tech score \d+/, { timeout: 120_000 });
  await page.getByLabel("Show").selectOption("flagged");
  await expect(soft).toBeVisible();
  await expect(clean).toHaveCount(0);

  // Clip page: the panel explains the flags, and the QC lane jumps to the silence.
  await soft.click();
  const panel = page.getByRole("region", { name: "Technical quality" });
  await expect(panel.getByRole("list", { name: "QC flag list" })).toContainText("Soft picture");
  await expect(panel).toContainText(/(blur measure 0\.\d+, limit at most 0\.55|detail measure [\d.]+, limit at least 5\.3)/);
  await expect(panel).toContainText(/Long silence\s*0:01\.\d\d–0:04\.\d\d/);
  await expect(panel).toContainText("not a judgement of the shot");
  const player = page.getByTestId("player");
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);
  await page.getByRole("group", { name: "QC flags" }).getByRole("button", { name: /^Long silence/ }).click();
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(1, 1);
});
