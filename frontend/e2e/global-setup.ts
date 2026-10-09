import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { FOOTAGE_DIR } from "./footage";

/** Tiny synthetic clips (no real footage): one ProRes .mov that browsers cannot play natively,
 * one H.264 mp4, a corrupt file, and a clip with two known cuts. */
export default function globalSetup() {
  rmSync(FOOTAGE_DIR, { recursive: true, force: true });
  mkdirSync(FOOTAGE_DIR, { recursive: true });
  const ff = (...args: string[]) =>
    execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...args], { stdio: "pipe" });
  const video = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=3"];
  const tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"];
  ff(...video, ...tone, "-c:v", "prores_ks", "-c:a", "pcm_s16le", join(FOOTAGE_DIR, "prores_clip.mov"));
  ff(...video, ...tone, "-c:v", "libx264", "-c:a", "aac", join(FOOTAGE_DIR, "h264_clip.mp4"));
  writeFileSync(join(FOOTAGE_DIR, "broken.mp4"), Buffer.alloc(4096, 7));
  // Three visually distinct segments: cuts at exactly 2.0 s and 4.0 s (ground truth for shots).
  const part = (source: string) => ["-f", "lavfi", "-i", `${source}=size=320x240:rate=25:duration=2`];
  ff(
    ...part("testsrc2"),
    ...part("smptebars"),
    ...part("rgbtestsrc"),
    ...["-f", "lavfi", "-i", "sine=frequency=330:duration=6"],
    ...["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]", "-map", "3:a"],
    ...["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", join(FOOTAGE_DIR, "three_shots.mp4")],
  );
}
