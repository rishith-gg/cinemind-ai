import { expect, test } from "@playwright/test";

// The end-to-end data folder has no speech model, so no clip has a transcript: the Script page
// must read the screenplay, say honestly that no line was found, and not offer an empty assembly.
test("a screenplay is read, its lines are listed with why none was found, and it can be replaced", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/projects");
  await page.getByLabel("Project name").fill(`Script ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Script", exact: true }).click();

  await page.getByLabel("Screenplay").fill("INT. LAB - NIGHT\n\nTHOM\n(quietly)\nYou're a jerk.\n\nCELIA\nLook, we have to follow our passions.\n");
  await page.getByRole("button", { name: "Find the lines in the footage" }).click();
  await expect(page.getByRole("status", { name: "Script summary" })).toContainText("0 of 2 dialogue lines have a take");
  await expect(page.getByRole("status", { name: "Script summary" })).toContainText("scored by words only");
  const lines = page.getByRole("list", { name: "Script lines" });
  await expect(lines.getByRole("heading", { name: "INT. LAB - NIGHT" })).toBeVisible();
  await expect(lines.getByRole("listitem", { name: "Line 1" })).toContainText("THOM: You're a jerk.");
  await expect(lines.getByRole("listitem", { name: "Line 1" })).toContainText("No take used: not found in any transcript.");
  await expect(page.getByRole("button", { name: "Build script assembly" })).toBeDisabled();

  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Replace script" }).click();
  await page.getByLabel("Screenplay").fill("Anna: Hello there.");
  await page.getByRole("button", { name: "Find the lines in the footage" }).click();
  await expect(page.getByRole("status", { name: "Script summary" })).toContainText("0 of 1 dialogue lines");
  await expect(lines.getByRole("listitem", { name: "Line 1" })).toContainText("Anna: Hello there.");
});
