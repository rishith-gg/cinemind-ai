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

it("lists the project's shots with links that open the clip at the shot", async () => {
  useCurrentProject.setState({ id: "p1" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(SHOTS.map((s) => ({ ...s, filename: "cuts.mp4" })))));
  wrap(<ShotsPage />);
  const link = await screen.findByRole("link", { name: "Open cuts.mp4, shot 2" });
  expect(link).toHaveAttribute("href", "/library/m1?t=2");
  expect(screen.getByText(/3 shots in 1 clip\./)).toBeInTheDocument();
});

it("asks for a project, and explains an empty shot list", async () => {
  const { unmount } = wrap(<ShotsPage />);
  expect(screen.getByText("No project selected")).toBeInTheDocument();
  unmount();
  useCurrentProject.setState({ id: "p1" });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
  wrap(<ShotsPage />);
  expect(await screen.findByText("No shots yet")).toBeInTheDocument();
});

it("formats positions and frame rates", () => {
  expect(formatTime(3.52)).toBe("0:03.52");
  expect(formatTime(75.5)).toBe("1:15.50");
  expect(rateLabel(30000, 1001)).toBe("29.97");
  expect(rateLabel(24000, 1001)).toBe("23.976");
  expect(rateLabel(60, 1)).toBe("60");
});
