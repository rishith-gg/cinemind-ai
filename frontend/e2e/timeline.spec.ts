import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

// The end-to-end data folder has no picture or text models: a brief without a subject takes
// every usable shot, which needs none. Checks the whole path: brief -> rough cut -> editor
// (why, trim, remove, play) -> export with markers.
test("a brief becomes an AI-assisted rough cut that can be edited, played and exported", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Rough cut ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();
  for (const name of ["three_shots.mp4", "h264_clip.mp4", "prores_clip.mov"])
    await expect(page.getByRole("link", { name: `Open ${name}`, exact: true })).toContainText("Ready", { timeout: 120_000 });

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Timeline" }).click();
  await page.getByLabel("Brief").fill("10 seconds, best first");
  await page.getByRole("button", { name: "Build rough cut" }).click();

  // The editor opens with the banner, how the brief was read, and the clips with their reasons.
  await expect(page.getByRole("note").first()).toHaveText("AI-assisted rough cut. Human review required.", { timeout: 60_000 });
  await expect(page.getByText(/read as length: 10 s · order: best first/)).toBeVisible();
  const clips = page.getByRole("list", { name: "Timeline clips" });
  const count = await clips.getByRole("listitem").count();
  expect(count).toBeGreaterThan(1);
  const first = clips.getByRole("listitem").first();
  await first.getByText("Why this clip").click();
  await expect(first).toContainText(/Result 1 of \d+/);
  await expect(first.getByRole("table", { name: "Score breakdown" })).toContainText("Technical quality");

  // Trim with the keyboard: one frame later in-point, saved and kept after a reload.
  const label = (await first.locator("p.truncate").textContent()) ?? "";
  const inPoint = first.getByRole("slider", { name: "In point" });
  await inPoint.focus();
  await page.keyboard.press("ArrowRight");
  await expect(first.locator("p.truncate")).not.toHaveText(label, { timeout: 10_000 });
  const trimmed = (await first.locator("p.truncate").textContent()) ?? "";
  await page.reload();
  await expect(clips.getByRole("listitem").first().locator("p.truncate")).toHaveText(trimmed);

  // The player plays through the proxies.
  await page.getByRole("button", { name: "Play timeline" }).click();
  const player = page.getByTestId("timeline-player");
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 15_000 }).toBeGreaterThan(0.2);
  await page.getByRole("button", { name: "Pause" }).click();

  // Remove a clip, then export: every clip carries a marker saying why it was chosen.
  await clips.getByRole("listitem").last().getByRole("button", { name: "Remove" }).click();
  await expect(clips.getByRole("listitem")).toHaveCount(count - 1);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download FCP7 XML (DaVinci Resolve)" }).click(),
  ]);
  const xml = readFileSync(await download.path(), "utf8");
  expect(xml).toContain("<!-- AI-assisted rough cut. Human review required. -->");
  expect(xml.match(/<marker>/g)).toHaveLength(count - 1);
  expect(xml).toContain("e2e-footage/"); // the originals, not the proxies

  // The new cut is listed on the Timeline page.
  await page.getByRole("link", { name: "← Rough cuts" }).click();
  await expect(page.getByRole("link", { name: /AI-assisted rough cut · \d+ clips/ })).toBeVisible();
});
