import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { TimelineDetail } from "../../api";
import { client } from "../../api/client.gen";
import { Toaster } from "../../components/Toaster";
import { useCurrentProject } from "../../lib/currentProject";
import { useToasts } from "../../lib/toast";
import { item } from "./testItems";
import { TimelineEditorPage } from "./TimelineEditor";
import { TimelinePage } from "./TimelinePage";

const reason = {
  rank: 1,
  summary: "Result 1 of 4; found by picture (#1); quality 0.88.",
  found_by: { visual: 1 },
  matched_line: "walking into the forest now",
  breakdown: { relevance: { value: 1, weight: 1, contribution: 1 } },
  trim: { how: "speech", detail: "keeps 1 whole spoken line(s) with 0.25 s of room", lines: ["walking into the forest now"] },
};

const timeline: TimelineDetail = {
  id: "t1",
  project_id: "p1",
  name: "Rough cut: forest",
  kind: "rough_cut",
  fps_num: 25,
  fps_den: 1,
  width: 1920,
  height: 1080,
  params: { banner: "AI-assisted rough cut. Human review required.", brief: "forest walk", understood: ["looking for: forest walk"], target_s: 60, order: "chronological", left_out: [] },
  created_at: "2026-10-15T00:00:00Z",
  item_count: 2,
  duration_frames: 100,
  duration_s: 4,
  warnings: [],
  export_dir: "/data/projects/p1/exports",
  formats: ["fcp7xml", "edl", "otio", "srt"],
  items: [item("a", 0, 2, { reason }), item("b", 4, 6, { filename: "IMG_2.MOV", scene_id: "sc1" })],
  alternatives: [
    { shot_id: "alt", media_id: "m1", filename: "IMG_3.MOV", start_s: 6, end_s: 8, scene_id: "sc1", keyframe_id: null, summary: "Result 3 of 4.", rank: 3 },
  ],
};

beforeEach(() => {
  client.setConfig({ baseUrl: "http://localhost" });
  useCurrentProject.setState({ id: "p1" });
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useCurrentProject.setState({ id: null });
  useToasts.setState({ toasts: [] });
});

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/timeline/:timelineId" element={<TimelineEditorPage />} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("sends the brief with the chosen options and opens the rough cut", async () => {
  const calls: { path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      calls.push({ path, body: input.method === "POST" ? await input.json() : undefined });
      if (path.endsWith("/actors")) return Response.json({ actors: [{ id: "a1", name: "Ravi", named: true }], set_aside: [] });
      if (path.endsWith("/scenes")) return Response.json({ scenes: [], ungrouped: [] });
      if (path.endsWith("/rough-cut")) return Response.json(timeline, { status: 201 });
      if (path === "/api/timelines/t1") return Response.json(timeline);
      return Response.json([]);
    }),
  );
  renderAt("/timeline");
  expect(await screen.findByText("No timelines yet")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Brief"), "forest walk");
  await userEvent.type(screen.getByLabelText("Length in minutes (optional)"), "1.5");
  await userEvent.selectOptions(screen.getByLabelText("Order"), "scene");
  await userEvent.selectOptions(await screen.findByLabelText("Only shots with"), "a1");
  await userEvent.click(screen.getByRole("button", { name: "Build rough cut" }));
  expect(await screen.findByRole("note")).toHaveTextContent("AI-assisted rough cut. Human review required.");
  const sent = calls.find((c) => c.path.endsWith("/rough-cut"))?.body;
  expect(sent).toEqual({ brief: "forest walk", target_s: 90, order: "scene", actor_id: "a1" });
});

it("shows each clip with why it was chosen, and saves removals and swaps", async () => {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      if (input.method !== "GET") sent.push({ method: input.method, path, body: await input.json() });
      if (input.method === "PATCH") return Response.json({ ...timeline, items: [timeline.items[1]], item_count: 1 });
      return Response.json(timeline);
    }),
  );
  renderAt("/timeline/t1");
  const clips = await screen.findByRole("list", { name: "Timeline clips" });
  const first = within(within(clips).getByRole("listitem", { name: "Clip 1: IMG_1.MOV" }));
  expect(first.getByText(/0:00.00–0:02.00 · 2.00 s · speech/)).toBeInTheDocument();
  await userEvent.click(first.getByText("Why this clip"));
  expect(first.getByText("Result 1 of 4; found by picture (#1); quality 0.88.")).toBeInTheDocument();
  expect(first.getByText("Found by: Picture #1")).toBeInTheDocument();
  expect(first.getByRole("table", { name: "Score breakdown" })).toHaveTextContent("Relevance");
  for (const f of ["FCP7 XML (DaVinci Resolve)", "EDL", "OTIO", "SRT subtitles"])
    expect(screen.getByRole("button", { name: `Download ${f}` })).toBeInTheDocument();

  // The second clip's suggestions list the same scene first.
  const second = within(within(clips).getByRole("listitem", { name: "Clip 2: IMG_2.MOV" }));
  expect(second.getByRole("option", { name: "#3 IMG_3.MOV 0:06.00 (same scene)" })).toBeInTheDocument();
  await userEvent.selectOptions(second.getByLabelText("Swap clip 2"), "alt");
  await waitFor(() => expect(sent.at(-1)).toEqual({ method: "POST", path: "/api/timelines/t1/items/b/swap", body: { shot_id: "alt" } }));

  await userEvent.click(first.getByRole("button", { name: "Remove" }));
  await waitFor(() =>
    expect(sent.at(-1)).toEqual({ method: "PATCH", path: "/api/timelines/t1", body: { items: [{ id: "b", source_in_s: 4, source_out_s: 6 }] } }),
  );
  await waitFor(() => expect(within(clips).getAllByRole("listitem")).toHaveLength(1));
});

it("shows the backend's message when an edit is refused", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (input.method === "PATCH")
        return Response.json({ code: "invalid_input", message: "A clip cannot end after its file does (10.00 s)." }, { status: 422 });
      return Response.json(timeline);
    }),
  );
  renderAt("/timeline/t1");
  const clips = await screen.findByRole("list", { name: "Timeline clips" });
  await userEvent.click(within(clips).getAllByRole("button", { name: "Remove" })[0]!);
  expect(await screen.findByText("A clip cannot end after its file does (10.00 s).")).toBeInTheDocument();
});

it("saves a trim when the slider is let go, on the frame grid", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (input.method === "PATCH") sent.push(await input.json());
      return Response.json(timeline);
    }),
  );
  renderAt("/timeline/t1");
  const clips = await screen.findByRole("list", { name: "Timeline clips" });
  const slider = within(clips).getAllByRole("slider", { name: "In point" })[0]!;
  fireEvent.change(slider, { target: { value: "0.51" } });
  expect(sent).toHaveLength(0); // nothing saved while dragging
  fireEvent.pointerUp(slider);
  await waitFor(() => expect(sent).toEqual([{ items: [{ id: "a", source_in_s: 0.52, source_out_s: 2 }, { id: "b", source_in_s: 4, source_out_s: 6 }] }]));
});
