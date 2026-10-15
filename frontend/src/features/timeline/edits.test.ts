import { expect, it } from "vitest";

import type { AlternativeOut, TimelineDetail } from "../../api";
import { clampTrim, moveItem, snap, suggestionsFor, toEdits, withItems } from "./edits";
import { item } from "./testItems";

const FRAME = 1 / 25;

it("moves an item and lists the edits in the new order", () => {
  const items = [item("a", 0, 1), item("b", 1, 2), item("c", 2, 3)];
  const moved = moveItem(items, 2, 0);
  expect(moved.map((i) => i.id)).toEqual(["c", "a", "b"]);
  expect(items.map((i) => i.id)).toEqual(["a", "b", "c"]); // the original is untouched
  expect(toEdits(moved)[0]).toEqual({ id: "c", source_in_s: 2, source_out_s: 3 });
});

it("keeps a trim on the frame grid, inside the file and at least one frame long", () => {
  const clip = item("a", 2, 4);
  expect(clampTrim(clip, "in", 2.51, FRAME)).toEqual([2.52, 4]);
  expect(clampTrim(clip, "in", -3, FRAME)).toEqual([0, 4]);
  expect(clampTrim(clip, "in", 9, FRAME)[0]).toBeCloseTo(4 - FRAME);
  expect(clampTrim(clip, "out", 99, FRAME)).toEqual([2, 10]);
  expect(clampTrim(clip, "out", 1, FRAME)[1]).toBeCloseTo(2 + FRAME);
  expect(snap(1.019, FRAME)).toBeCloseTo(1.0);
});

it("recomputes record positions so the timeline stays gapless", () => {
  const t = { fps_num: 25, fps_den: 1, items: [] } as unknown as TimelineDetail;
  const out = withItems(t, [item("a", 0, 2), item("b", 5, 5.52)]);
  expect(out.items.map((i) => [i.record_frame, i.duration_frames])).toEqual([
    [0, 50],
    [50, 13],
  ]);
  expect(out.duration_frames).toBe(63);
  expect(out.item_count).toBe(2);
});

it("offers suggestions from the clip's own scene first, then by rank", () => {
  const alt = (shot_id: string, scene_id: string | null, rank: number): AlternativeOut => ({
    shot_id,
    media_id: "m",
    filename: "f",
    start_s: 0,
    end_s: 2,
    scene_id,
    keyframe_id: null,
    summary: "",
    rank,
  });
  const found = suggestionsFor(item("a", 0, 1, { scene_id: "x" }), [alt("1", "y", 1), alt("2", "x", 5), alt("3", null, 2)]);
  expect(found.map((a) => a.shot_id)).toEqual(["2", "1", "3"]);
});
