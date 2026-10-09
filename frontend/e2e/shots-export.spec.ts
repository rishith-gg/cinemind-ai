import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

test("shots are detected, shown on the clip, and export as a timeline for the editor", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Shots ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();
  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();

  const card = page.getByRole("link", { name: "Open three_shots.mp4" });
  await expect(card).toContainText("Ready", { timeout: 120_000 });
  await expect(page.getByRole("link", { name: "Open h264_clip.mp4" })).toContainText("Ready", { timeout: 120_000 });
  await expect(page.getByRole("link", { name: "Open prores_clip.mov" })).toContainText("Ready", { timeout: 120_000 });

  // Clip page: three shots with the real cut positions; clicking one seeks the player to it.
  await card.click();
  const strip = page.getByRole("list", { name: "Shots" });
  await expect(strip.getByRole("button")).toHaveCount(3, { timeout: 30_000 });
  await expect(strip.getByRole("button", { name: "Shot 2: 0:02.00 to 0:04.00" })).toBeVisible();
  await expect(page.getByText(/3 shots over 0:06.00 · detected by PySceneDetect/)).toBeVisible();
  const player = page.getByTestId("player");
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);
  await strip.getByRole("button", { name: /^Shot 3:/ }).click();
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(4, 1);
  await expect(strip.getByRole("button", { name: /^Shot 3:/ })).toHaveAttribute("aria-current", "true");

  // Shots page: every shot of the project, with a keyframe image that really loads.
  await page.getByRole("link", { name: "Shots / Scenes" }).click();
  await expect(page.getByRole("link", { name: /^Open three_shots\.mp4, shot/ })).toHaveCount(3);
  await expect(page.getByRole("link", { name: "Open h264_clip.mp4, shot 1" })).toBeVisible();
  const image = page.getByRole("link", { name: "Open three_shots.mp4, shot 2" }).locator("img");
  await expect.poll(() => image.evaluate((i: HTMLImageElement) => i.naturalWidth)).toBeGreaterThan(0);
  await page.getByRole("link", { name: "Open three_shots.mp4, shot 2" }).click();
  await expect.poll(() => page.getByTestId("player").evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(2, 1);

  // Export page: build the all-shots timeline and download it.
  await page.getByRole("link", { name: "Export", exact: true }).click();
  await expect(page.getByText("No timelines yet")).toBeVisible();
  await page.getByRole("button", { name: "Build timeline" }).click();
  const timeline = page.getByRole("listitem", { name: "All shots" });
  await expect(timeline).toContainText("5 cuts · 0:12 · 25 fps");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    timeline.getByRole("button", { name: "Download FCP7 XML (DaVinci Resolve)" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^All shots_[0-9a-f]{8}\.xml$/);
  const xml = readFileSync(await download.path(), "utf8");
  expect(xml).toContain("<!DOCTYPE xmeml>");
  expect(xml).toContain("e2e-footage/three_shots.mp4</pathurl>"); // the original, not the proxy
  expect(xml.match(/<clipitem id="clipitem-\d+-v">/g)).toHaveLength(5);
  expect(xml).toContain("<in>50</in>"); // second shot starts at frame 50 of its source

  const [edl] = await Promise.all([
    page.waitForEvent("download"),
    timeline.getByRole("button", { name: "Download EDL" }).click(),
  ]);
  const events = readFileSync(await edl.path(), "utf8").split("\n").filter((l) => /^\d{3} /.test(l));
  expect(events).toHaveLength(5);
  expect(events.some((l) => l.includes("00:00:02:00 00:00:04:00"))).toBe(true);

  page.once("dialog", (d) => void d.accept());
  await timeline.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("No timelines yet")).toBeVisible();
});
