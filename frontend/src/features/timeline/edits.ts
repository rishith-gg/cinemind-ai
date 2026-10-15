import type { AlternativeOut, TimelineDetail, TimelineItemEdit, TimelineItemOut } from "../../api";

/** Items as the PATCH body wants them: the whole list, in order, with in/out points. */
export function toEdits(items: TimelineItemOut[]): TimelineItemEdit[] {
  return items.map((i) => ({ id: i.id, source_in_s: i.source_in_s, source_out_s: i.source_out_s }));
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  const next = items.slice();
  const [moved] = next.splice(from, 1);
  if (moved !== undefined) next.splice(to, 0, moved);
  return next;
}

/** Seconds of one timeline frame. */
export function frameSeconds(t: Pick<TimelineDetail, "fps_num" | "fps_den">): number {
  return t.fps_den / t.fps_num;
}

/** Snap to the timeline's frame grid (in/out points are frames once exported). */
export function snap(seconds: number, frame: number): number {
  return Math.round(seconds / frame) * frame;
}

/** A new in or out point kept inside the file and at least one frame from the other point. */
export function clampTrim(item: TimelineItemOut, edge: "in" | "out", seconds: number, frame: number): [number, number] {
  const end = item.media_duration_s ?? item.source_out_s;
  if (edge === "in") {
    const value = Math.min(Math.max(0, snap(seconds, frame)), item.source_out_s - frame);
    return [value, item.source_out_s];
  }
  const value = Math.max(Math.min(end, snap(seconds, frame)), item.source_in_s + frame);
  return [item.source_in_s, value];
}

/** Optimistic copy of the timeline with new items: record positions recomputed, gapless. */
export function withItems(t: TimelineDetail, items: TimelineItemOut[]): TimelineDetail {
  const rate = t.fps_num / t.fps_den;
  let record = 0;
  const placed = items.map((item, position) => {
    const frames = Math.max(1, Math.round(item.source_out_s * rate) - Math.round(item.source_in_s * rate));
    const out = { ...item, position, record_frame: record, duration_frames: frames };
    record += frames;
    return out;
  });
  return { ...t, items: placed, item_count: placed.length, duration_frames: record, duration_s: record / rate };
}

/** Suggestions for one clip: those from its scene first, then by search rank. */
export function suggestionsFor(item: TimelineItemOut, alternatives: AlternativeOut[]): AlternativeOut[] {
  const scene = item.scene_id ?? null;
  const near = (a: AlternativeOut) => (scene !== null && a.scene_id === scene ? 0 : 1);
  return alternatives.slice().sort((a, b) => near(a) - near(b) || (a.rank ?? 1e9) - (b.rank ?? 1e9));
}
