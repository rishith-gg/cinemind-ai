import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { formatTime, rateLabel } from "../library/format";
import { ShotsPage } from "./ShotsPage";
import { ShotStrip } from "./ShotStrip";

const detection = { library: "PySceneDetect", detector: "adaptive", threshold: 3 };
const shot = (index: number, start_s: number, end_s: number) => ({
  id: `s${index}`,
  media_id: "m1",
  index,
  start_frame: start_s * 25,
  end_frame: end_s * 25,
  start_s,
  end_s,
  fps_num: 25,
  fps_den: 1,
  detection,
  keyframes: [{ id: `k${index}`, slot: 0, frame: start_s * 25 + 3, time_s: start_s + 0.12, sharpness: 12 }],
});
const SHOTS = [shot(0, 0, 2), shot(1, 2, 3.52), shot(2, 3.52, 8)];

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

it("shows each shot, marks the one playing, says how it was detected, and seeks on click", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SHOTS)));
  const onSeek = vi.fn();
  wrap(<ShotStrip mediaId="m1" duration={8} time={2.5} onSeek={onSeek} />);
  const second = await screen.findByRole("button", { name: "Shot 2: 0:02.00 to 0:03.52" });
  expect(second).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("button", { name: /^Shot 1:/ })).not.toHaveAttribute("aria-current");
  expect(screen.getByText(/3 shots over 0:08.00 · detected by PySceneDetect \(adaptive, threshold 3\)/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^Shot 3:/ }));
  expect(onSeek).toHaveBeenCalledWith(3.52);
});

it("says so when a clip has no shots yet", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
  wrap(<ShotStrip mediaId="m1" duration={8} time={0} onSeek={() => undefined} />);
  expect(await screen.findByText("Shots have not been detected yet.")).toBeInTheDocument();
});

const sceneShot = (index: number, start_s: number, end_s: number, extra: Record<string, unknown> = {}) => ({
  shot_id: `s${index}`,
  media_id: "m1",
  filename: "cuts.mp4",
  index,
  start_s,
  end_s,
  keyframe_id: `k${index}`,
  visual: index ? 0.91 : null,
  color: index ? 0.62 : null,
  combined: index ? 0.82 : null,
  decision: index ? "similar (0.82 \u2265 0.8)" : "first shot",
  edit: null,
  ...extra,
});
const scenes = (overrides: Record<string, unknown> = {}) => ({
  scenes: [
    { id: "c1", index: 0, name: "Scene 001", named: false, shot_count: 2, duration_s: 3.52, shots: [sceneShot(0, 0, 2), sceneShot(1, 2, 3.52)] },
    {
      id: "c2",
      index: 1,
      name: "Scene 002",
      named: false,
      shot_count: 1,
      duration_s: 4.48,
      shots: [sceneShot(2, 3.52, 8, { combined: 0.4, decision: "split by you", edit: "split" })],
    },
  ],
  ungrouped: [],
  grouped_at: "2026-10-14T10:00:00Z",
  details: { shots: 3 },
  settings: { join_similarity: 0.8, visual_weight: 0.7, color_weight: 0.3 },
  model_missing: false,
  message: null,
  ...overrides,
});

it("groups shots into scenes, says why, and links each shot to its place in the clip", async () => {
  useCurrentProject.setState({ id: "p1" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(scenes())));
  wrap(<ShotsPage />);
  const link = await screen.findByRole("link", { name: "Open cuts.mp4, shot 2" });
  expect(link).toHaveAttribute("href", "/library/m1?t=2");
  expect(screen.getByText(/3 shots in 1 clip, 2 scenes\./)).toBeInTheDocument();
  expect(screen.getByText(/joined at a similarity of 0.8 or more. That limit is a convention/)).toBeInTheDocument();
  expect(screen.getByText("similar (0.82 \u2265 0.8) · picture 0.91 · colour 0.62")).toBeInTheDocument();
  expect(screen.getByText("Starts here: split by you")).toBeInTheDocument();
});

it("splits, joins and renames scenes and shows the list the server returns", async () => {
  useCurrentProject.setState({ id: "p1" });
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const body: unknown = req.method === "GET" ? null : await req.json();
      calls.push({ method: req.method, url: req.url, body });
      if (req.method === "PATCH") return Response.json(scenes({ scenes: [{ ...scenes().scenes[0], name: "Walk home", named: true }] }));
      return Response.json(scenes());
    }),
  );
  wrap(<ShotsPage />);
  await userEvent.click(await screen.findByRole("button", { name: "Start a new scene at cuts.mp4, shot 2" }));
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { shot_id: "s1", decision: "split" } });
  await userEvent.click(screen.getByRole("button", { name: "Join with the scene before" }));
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { shot_id: "s2", decision: "join" } });
  await userEvent.click(screen.getAllByRole("button", { name: "Undo your edit" })[0]!);
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { shot_id: "s2", decision: "auto" } });
  const name = screen.getByRole("textbox", { name: "Name of Scene 001" });
  await userEvent.clear(name);
  await userEvent.type(name, "Walk home");
  await userEvent.click(screen.getAllByRole("button", { name: "Save name" })[0]!);
  expect(calls.at(-1)).toMatchObject({ method: "PATCH", url: expect.stringContaining("/api/scenes/c1"), body: { name: "Walk home" } });
  expect(await screen.findByRole("article", { name: "Walk home" })).toBeInTheDocument();
});

it("asks for a project, explains an empty list and a missing model", async () => {
  const { unmount } = wrap(<ShotsPage />);
  expect(screen.getByText("No project selected")).toBeInTheDocument();
  unmount();
  useCurrentProject.setState({ id: "p1" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(scenes({ scenes: [] }))));
  const second = wrap(<ShotsPage />);
  expect(await screen.findByText("No shots yet")).toBeInTheDocument();
  second.unmount();
  const message = "The picture model 'clip-vit-b32' is not downloaded, so shots cannot be compared.";
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(scenes({ model_missing: true, message }))));
  wrap(<ShotsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
});

it("formats positions and frame rates", () => {
  expect(formatTime(3.52)).toBe("0:03.52");
  expect(formatTime(75.5)).toBe("1:15.50");
  expect(rateLabel(30000, 1001)).toBe("29.97");
  expect(rateLabel(24000, 1001)).toBe("23.976");
  expect(rateLabel(60, 1)).toBe("60");
});
