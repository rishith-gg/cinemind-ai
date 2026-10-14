import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { TagOut } from "../../api";
import { client } from "../../api/client.gen";
import { hiddenReason, tagTitle } from "./labels";
import { TagsPanel } from "./TagsPanel";

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => vi.unstubAllGlobals());

const evaluation = { dataset: "places365", precision: 0.93, precision_ci95: [0.88, 0.96], recall: 0.71 };
const tag = (name: string, label: string, extra: Partial<TagOut> = {}): TagOut => ({
  name,
  label,
  group: "setting",
  group_label: "Indoor / outdoor",
  source: "model",
  score: 0.97,
  threshold: 0.9,
  status: "shown",
  review: null,
  visible: true,
  details: { evaluation, model: "clip-vit-b32" },
  ...extra,
});
const TAGS = {
  status: "done",
  model: "clip-vit-b32",
  message: null,
  calibrated: "2026-10-14",
  calibration_source: "eval/results/tag_calibration_clip-vit-b32_2026-10-14.json",
  shots: [
    {
      shot_id: "s0",
      index: 0,
      start_s: 0,
      end_s: 2,
      tags: [
        tag("outdoor", "Outdoor"),
        tag("faces", "2 clear faces", { source: "faces", group: "faces", group_label: "Faces", score: null, threshold: null, details: { rule: "most usable faces" } }),
        tag("beach", "Beach or coast", { group: "place", status: "below", visible: false, score: 0.2, threshold: 0.6 }),
        tag("wide", "Wide shot", { group: "shot_size", status: "not_evaluated", visible: false, threshold: null }),
        tag("day", "Daylight", { status: "disabled", visible: false, details: { evaluation: { reason: "held-out precision 0.61 < 0.85" } } }),
      ],
    },
    { shot_id: "s1", index: 1, start_s: 2, end_s: 5, tags: [] },
  ],
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

it("shows tags that passed their evaluated threshold and explains the hidden ones", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(TAGS)));
  const onSeek = vi.fn();
  wrap(<TagsPanel mediaId="m1" time={2.5} onSeek={onSeek} />);
  const tags = await screen.findByRole("list", { name: "Tags of shot 1" });
  expect(tags).toHaveTextContent("Outdoor 0.97");
  expect(tags).toHaveTextContent("2 clear faces");
  expect(tags).not.toHaveTextContent("Beach");
  expect(screen.getByText("3 hidden suggestions")).toBeInTheDocument();
  expect(screen.getByText("under its threshold (0.60) on most keyframes")).toBeInTheDocument();
  expect(screen.getByText("not evaluated (no labelled data to set a threshold)")).toBeInTheDocument();
  expect(screen.getByText("switched off: held-out precision 0.61 < 0.85")).toBeInTheDocument();
  expect(screen.getByText("No tag passed its evaluated threshold.")).toBeInTheDocument();
  expect(screen.getByText(/threshold set on labelled public photos \(2026-10-14\)/)).toBeInTheDocument();
  expect(screen.getByText(/not probabilities/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Jump to shot 2 at 0:02.00" }).closest("li")).toHaveAttribute("aria-current", "true");
  await userEvent.click(screen.getByRole("button", { name: "Jump to shot 2 at 0:02.00" }));
  expect(onSeek).toHaveBeenCalledWith(2);
});

it("sends approve and reject decisions and shows the result", async () => {
  const bodies: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      if (req.method === "PUT") {
        const body = (await req.json()) as { decision: string };
        bodies.push(body);
        if (body.decision !== "rejected") return Response.json(TAGS);
        const shots = [{ ...TAGS.shots[0]!, tags: [tag("outdoor", "Outdoor", { review: "rejected", visible: false })] }, TAGS.shots[1]!];
        return Response.json({ ...TAGS, shots });
      }
      return Response.json(TAGS);
    }),
  );
  wrap(<TagsPanel mediaId="m1" time={0} onSeek={() => undefined} />);
  await userEvent.click(await screen.findByRole("button", { name: "Approve Beach or coast anyway" }));
  expect(bodies.at(-1)).toEqual({ shot_id: "s0", name: "beach", decision: "approved" });
  await userEvent.click(screen.getByRole("button", { name: "Reject Outdoor" }));
  expect(bodies.at(-1)).toEqual({ shot_id: "s0", name: "outdoor", decision: "rejected" });
  expect(await screen.findByText("rejected by you")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Undo reject" }));
  expect(bodies.at(-1)).toEqual({ shot_id: "s0", name: "outdoor", decision: "none" });
});

it("says why a clip has no tags", async () => {
  const message = "The picture and text models are not downloaded.";
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...TAGS, status: "model_missing", model: null, message, shots: [] })));
  wrap(<TagsPanel mediaId="m1" time={0} onSeek={() => undefined} />);
  expect(await screen.findByRole("note")).toHaveTextContent(message);
});

it("puts the evaluation behind a tag into words", () => {
  const shown = tag("outdoor", "Outdoor", { details: { evaluation, top_places: [[["coast", 0.4]]] } });
  expect(tagTitle(shown)).toBe(
    "Indoor / outdoor: Outdoor · score 0.97 · threshold 0.90 · right 93% of the time when shown on single places365 photos (95% CI 88%–96%) · closest places (first keyframe): coast 0.40",
  );
  expect(hiddenReason(tag("x", "X", { review: "rejected" }))).toBe("rejected by you");
});
