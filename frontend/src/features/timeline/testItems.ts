import type { TimelineItemOut } from "../../api";

/** A timeline item for tests. */
export function item(id: string, inS: number, outS: number, extra: Partial<TimelineItemOut> = {}): TimelineItemOut {
  return {
    id,
    position: 0,
    media_id: "m1",
    shot_id: `s-${id}`,
    filename: "IMG_1.MOV",
    source_in_s: inS,
    source_out_s: outS,
    record_frame: 0,
    duration_frames: 0,
    source_fps_num: 25,
    source_fps_den: 1,
    mixed_rate: false,
    media_duration_s: 10,
    ...extra,
  };
}
