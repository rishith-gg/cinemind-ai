import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { LibraryPage } from "../library/LibraryPage";
import { explainFlag, flagLabel, scoreText } from "./labels";
import { QcLane } from "./QcLane";
import { QualityPanel } from "./QualityPanel";

const shot = {
  shot_id: "s1",
  index: 0,
  frames: 6,
  sharpness: 3.1,
  blur: 0.71,
  luma_mean: 0.48,
  luma_std: 0.2,
  spread: 0.7,
  clipped: 0,
  crushed: 0,
  sharpness_score: 0,
  exposure_score: 1,
  contrast_score: 1,
  score: 0.5,
};
const QUALITY = {
  media_id: "m1",
  measured: true,
  score: 0.44,
  low_quality: true,
  shots: [shot],
  audio: {
    integrated_lufs: -41.2,
    loudness_range: 3,
    true_peak_db: -20.5,
    sample_peak: 0.1,
    clipped_pct: 0,
    silence_s: 3,
    silence_pct: 30,
    score: 0,
    details: {},
  },
  flags: [
    { kind: "out_of_focus", source: "picture", shot_id: "s1", start_s: 0, end_s: 10, details: { metric: "blur", value: 0.71, threshold: 0.55, direction: "above" } },
    { kind: "long_silence", source: "audio", shot_id: null, start_s: 4, end_s: 7, details: { metric: "seconds", value: 3, threshold: 2, direction: "above" } },
    { kind: "low_audio_level", source: "audio", shot_id: null, start_s: 0, end_s: 10, details: { metric: "integrated_lufs", value: -41.2, threshold: -35, direction: "below" } },
    { kind: "black_frames", source: "picture", shot_id: null, start_s: 8, end_s: 9, details: { detector: "ffmpeg blackdetect" } },
  ],
  config: { weight_sharpness: 0.5, weight_exposure: 0.3, weight_contrast: 0.2, weight_audio: 0.25 },
  settings_changed: false,
};

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("explains the score: sub-scores, audio, each flag with its value and limit, and the formula", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(QUALITY)));
  wrap(<QualityPanel mediaId="m1" />);
  const panel = within(await screen.findByRole("region", { name: "Technical quality" }));
  expect(panel.getByText("44")).toBeInTheDocument();
  expect(panel.getByText(/\/ 100 · low/)).toBeInTheDocument();
  expect(panel.getByText(/loudness -41.2 LUFS · peak -20.5 dBFS · clipped 0.00% · silent 30%/)).toBeInTheDocument();
  const flags = within(panel.getByRole("list", { name: "QC flag list" }));
  expect(flags.getByText("Soft picture")).toBeInTheDocument();
  expect(flags.getByText("blur measure 0.71, limit at most 0.55")).toBeInTheDocument();
  expect(flags.getByText("loudness (LUFS) -41.2, limit at least -35")).toBeInTheDocument();
  expect(flags.getByText("found by ffmpeg blackdetect")).toBeInTheDocument();
  expect(panel.getByText(/weighted average of focus \(0.5\), exposure \(0.3\) and contrast \(\s*0.2\)/)).toBeInTheDocument();
  expect(panel.getByText(/blended with the audio score at 0.25/)).toBeInTheDocument();
  expect(panel.getByText(/not a\s+judgement of the shot/)).toBeInTheDocument();
  expect(panel.queryByRole("note")).not.toBeInTheDocument();
});

it("says when there is no score, when focus was not judged, and when settings changed since scoring", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...QUALITY, measured: false, score: null, shots: [], audio: null, flags: [] })));
  const first = wrap(<QualityPanel mediaId="m1" />);
  expect(await screen.findByText(/No technical score/)).toBeInTheDocument();
  first.unmount();
  const flat = { ...QUALITY, settings_changed: true, shots: [{ ...shot, index: 2, sharpness_score: null }] };
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(flat)));
  wrap(<QualityPanel mediaId="m1" />);
  expect(await screen.findByText("not judged")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "3" })).toBeInTheDocument(); // the shot's own number
  expect(screen.getByRole("note")).toHaveTextContent("settings have changed since this clip was scored");
});

it("places flags on the time axis and seeks to one when clicked", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(QUALITY)));
  const onSeek = vi.fn();
  wrap(<QcLane mediaId="m1" duration={10} onSeek={onSeek} />);
  const silence = await screen.findByRole("button", { name: "Long silence: 0:04.00 to 0:07.00" });
  expect(silence).toHaveStyle({ left: "40%", width: "30%" });
  expect(screen.getAllByRole("button")).toHaveLength(4);
  // one labelled row per kind, so flags over the same range do not cover each other
  expect(within(screen.getByRole("group", { name: "QC flags" })).getAllByRole("list")).toHaveLength(4);
  await userEvent.click(silence);
  expect(onSeek).toHaveBeenCalledWith(4);
});

const media = (id: string, filename: string, quality_score: number | null, low_quality: boolean, qc_flags: string[]) => ({
  id,
  filename,
  quality_score,
  low_quality,
  qc_flags,
  project_id: "p1",
  path: `/f/${filename}`,
  import_mode: "reference",
  size_bytes: 1000,
  content_hash: id,
  created_at: "2026-01-01T00:00:00Z",
  source_missing: false,
  probed: true,
  container: "mov",
  duration_s: 5,
  width: 1920,
  height: 1080,
  fps_num: 25,
  fps_den: 1,
  is_vfr: false,
  video_codec: "h264",
  audio_codec: null,
  bit_rate: null,
  audio_channels: null,
  audio_sample_rate: null,
  start_timecode: null,
  color: {},
  has_proxy: true,
  has_poster: false,
  has_strip: false,
  has_waveform: false,
  proxy_encoder: "libx264",
  strip_frames: 0,
  job: null,
});

it("shows score badges and flag chips in the library, and filters and sorts by them", async () => {
  useCurrentProject.setState({ id: "p1" });
  const items = [
    media("a", "good.mp4", 0.93, false, []),
    media("b", "soft.mp4", 0.41, true, ["out_of_focus"]),
    media("c", "silent.mp4", 0.8, false, ["long_silence"]),
    media("d", "pending.mp4", null, false, []),
  ];
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(items)));
  wrap(<LibraryPage />);
  const soft = within(await screen.findByRole("link", { name: "Open soft.mp4" }));
  expect(soft.getByText("Tech score 41 · low")).toBeInTheDocument();
  expect(soft.getByText("Soft picture")).toBeInTheDocument();
  // the card's description points at the score and flags, so they are read out with the card
  const described = screen.getByRole("link", { name: "Open soft.mp4" }).getAttribute("aria-describedby");
  expect(document.getElementById(described ?? "")).toHaveTextContent("Tech score 41 · low");
  expect(document.getElementById(described ?? "")).toHaveTextContent("Soft picture");
  const names = () => screen.getAllByRole("link", { name: /^Open / }).map((l) => l.getAttribute("aria-label"));
  expect(screen.getByRole("option", { name: "With QC flags (2)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Low technical score (1)" })).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Show"), "Low technical score (1)");
  expect(names()).toEqual(["Open soft.mp4"]);
  await userEvent.selectOptions(screen.getByLabelText("Show"), "Scored, no QC flags (1)");
  expect(names()).toEqual(["Open good.mp4"]);
  await userEvent.selectOptions(screen.getByLabelText("Show"), "All clips (4)");
  await userEvent.selectOptions(screen.getByLabelText("Sort"), "Technical score: lowest first");
  expect(names()).toEqual(["Open soft.mp4", "Open silent.mp4", "Open good.mp4", "Open pending.mp4"]);
});

it("names flags and scores in plain words", () => {
  expect(flagLabel("frozen_frames")).toBe("Frozen picture");
  expect(flagLabel("some_new_kind")).toBe("some new kind");
  expect(scoreText(0.876)).toBe("88");
  expect(scoreText(null)).toBe("–");
  expect(flagLabel("audio_unreadable")).toBe("Audio not analysed");
  expect(explainFlag({ details: { reason: "The audio track could not be decoded." } })).toBe("The audio track could not be decoded.");
  expect(explainFlag({ details: { metric: "integrated_lufs", value: null, threshold: -35, direction: "below" } })).toBe(
    "loudness (LUFS) silent, limit at least -35",
  );
});
