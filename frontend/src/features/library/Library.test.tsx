import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { formatFps, mediaStatus } from "./format";
import { LibraryPage } from "./LibraryPage";
import { summarize } from "./ImportPanel";

vi.mock("wavesurfer.js", () => ({ default: { create: vi.fn(() => ({ destroy: vi.fn() })) } }));

const base = {
  project_id: "p1",
  path: "/f/a.mp4",
  import_mode: "reference",
  size_bytes: 2_000_000,
  content_hash: "h",
  created_at: "2026-01-01T00:00:00Z",
  source_missing: false,
  probed: true,
  container: "mov",
  duration_s: 65,
  width: 1920,
  height: 1080,
  fps_num: 30000,
  fps_den: 1001,
  is_vfr: false,
  video_codec: "prores",
  audio_codec: "pcm_s16le",
  bit_rate: null,
  audio_channels: 2,
  audio_sample_rate: 48000,
  start_timecode: null,
  color: {},
  has_proxy: true,
  has_poster: true,
  has_strip: true,
  has_waveform: true,
  proxy_encoder: "libx264",
  strip_frames: 20,
  quality_score: null,
  low_quality: false,
  qc_flags: [],
  transcript_status: null,
  transcript_language: null,
  job: null,
};

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

function renderLibrary() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("asks for a project when none is selected", () => {
  renderLibrary();
  expect(screen.getByText(/No project selected/)).toBeInTheDocument();
});

it("lists clips with status, and shows failures in plain language", async () => {
  useCurrentProject.setState({ id: "p1" });
  const items = [
    { ...base, id: "m1", filename: "a.mp4" },
    {
      ...base,
      id: "m2",
      filename: "bad.mp4",
      has_proxy: false,
      has_poster: false,
      probed: false,
      job: { id: "j", status: "failed", progress: 0, error_code: "unreadable_media", error_message: "bad.mp4 could not be read as video or audio." },
    },
  ];
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(items)));
  renderLibrary();
  expect(await screen.findByLabelText("Open a.mp4")).toBeInTheDocument();
  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByText("Failed")).toBeInTheDocument();
  expect(screen.getByText(/could not be read as video or audio/)).toBeInTheDocument();
});

it("shows an empty state for a project without footage", async () => {
  useCurrentProject.setState({ id: "p1" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
  renderLibrary();
  expect(await screen.findByText("No footage yet")).toBeInTheDocument();
});

it("formats exact rational frame rates and statuses", () => {
  expect(formatFps({ fps_num: 30000, fps_den: 1001, is_vfr: false })).toBe("30000/1001 (29.97)");
  expect(formatFps({ fps_num: 25, fps_den: 1, is_vfr: true })).toBe("25, variable");
  const m = { ...base, id: "x", filename: "x" };
  expect(mediaStatus({ ...m, source_missing: true, has_proxy: false })).toBe("missing");
  expect(mediaStatus({ ...m, job: { id: "j", status: "running", progress: 0.5, error_code: null, error_message: null } })).toBe("processing");
});

it("summarizes an import batch honestly", () => {
  const text = summarize([
    { path: "a", duplicate: false, media: { ...base, id: "1", filename: "a" } },
    { path: "b", duplicate: true, media: { ...base, id: "2", filename: "b" } },
    { path: "c", duplicate: false, error_code: "unreadable_media", error_message: "c is corrupt" },
  ]);
  expect(text).toBe("Imported 1 file, 1 already in the project, 1 could not be imported (c is corrupt).");
});
