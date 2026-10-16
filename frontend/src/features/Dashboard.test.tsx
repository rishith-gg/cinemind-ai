import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ProjectStatsOut } from "../api";
import { client } from "../api/client.gen";
import { useCurrentProject } from "../lib/currentProject";
import { DashboardPage } from "./DashboardPage";

const stats: ProjectStatsOut = {
  clips: 25, duration_s: 532.1, size_bytes: 2397738453, states: { succeeded: 24, failed: 1 },
  codecs: { h264: 14, hevc: 11 }, portrait: 12, landscape: 13, variable_rate: 2, no_audio: 2,
  frame_rates: ["24", "25", "29.97"], shots: 76, scenes: 72, quality_bands: [1, 0, 3, 14, 58],
  quality_measured: 76, low_quality: 3, low_quality_below: 0.5, qc_flags: { underexposed: 11, low_audio_level: 4 },
  transcripts: { done: 9, no_speech: 14 }, languages: { en: 3, kn: 4 }, speech_s: 223.7, segments: 31,
  actors: 15, actors_named: 2, take_groups: 2, shots_in_takes: 4, selected: 5, rejected: 1, timelines: { rough_cut: 1 },
};

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

function stub(body: ProjectStatsOut) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname;
      if (path === "/api/projects") return Response.json([{ id: "p1", name: "Shoot", description: "", created_at: "", updated_at: "" }]);
      if (path === "/api/projects/p1") return Response.json({ id: "p1", name: "Shoot", description: "", created_at: "", updated_at: "" });
      return Response.json(body);
    }),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows the project's footage statistics", async () => {
  useCurrentProject.setState({ id: "p1" });
  stub(stats);
  renderPage();
  expect(await screen.findByRole("link", { name: /Clips\s*25/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Shots\s*76\s*72 scenes/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Low-quality shots\s*3/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /0.8–1: 58/ })).toBeInTheDocument();
  const processing = within(screen.getByRole("region", { name: "Processing" }));
  expect(processing.getByText("processed")).toBeInTheDocument();
  expect(processing.getByText(/Open the failed clips/)).toBeInTheDocument();
  expect(screen.getByText("underexposed")).toBeInTheDocument();
  expect(screen.getByText("language: kn")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Name the actors" })).toBeInTheDocument();
  expect(screen.queryByText(/Phase 3/)).toBeNull();
});

it("asks to import footage for an empty project and to choose one without a project", async () => {
  useCurrentProject.setState({ id: "p1" });
  stub({ ...stats, clips: 0 });
  renderPage();
  expect(await screen.findByText("Shoot has no footage yet")).toBeInTheDocument();
});

it("asks to choose a project when none is selected", async () => {
  stub(stats);
  renderPage();
  expect(await screen.findByText("No project selected")).toBeInTheDocument();
});
