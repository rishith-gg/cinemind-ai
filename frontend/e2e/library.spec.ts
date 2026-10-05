import { expect, test } from "@playwright/test";

import { FOOTAGE_DIR } from "./footage";

test("import a folder, play a non-browser format via its proxy, see a friendly error", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Library ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: "Open library" }).click();

  await page.getByRole("button", { name: "Import footage" }).click();
  await page.getByRole("button", { name: /e2e-footage/ }).click();
  await page.getByRole("button", { name: "Import this whole folder" }).click();

  const card = (name: string) => page.getByRole("link", { name: `Open ${name}` });
  await expect(card("prores_clip.mov")).toContainText("Ready", { timeout: 90_000 });
  await expect(card("h264_clip.mp4")).toContainText("Ready", { timeout: 90_000 });
  await expect(card("broken.mp4")).toContainText("could not be read as video or audio", { timeout: 60_000 });
  await expect(card("broken.mp4")).toContainText("Failed");

  // The ProRes file is not playable by any browser: the player must be using the H.264 proxy.
  await card("prores_clip.mov").click();
  const player = page.getByTestId("player");
  await expect(player).toBeVisible();
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(2);
  const duration = await player.evaluate((v: HTMLVideoElement) => v.duration);
  expect(duration).toBeGreaterThan(2.5);
  expect(duration).toBeLessThan(3.5);
  await expect(page.getByText("prores", { exact: true })).toBeVisible(); // source codec in metadata

  // keyboard: play with Space, then step a frame with the arrow key
  await page.keyboard.press("Space");
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0.2);
  await page.keyboard.press("Space");
  const t0 = await player.evaluate((v: HTMLVideoElement) => v.currentTime);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => player.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(t0 + 0.04, 2);

  // seeking works because the backend answers Range requests
  const status = await page.evaluate(async (url) => {
    const r = await fetch(url, { headers: { Range: "bytes=0-99" } });
    return r.status;
  }, await player.getAttribute("src"));
  expect(status).toBe(206);
  expect(FOOTAGE_DIR).toContain("e2e-footage");
});
