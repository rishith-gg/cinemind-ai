import type { QcFlagOut } from "../../api";

/** Plain-language names for QC flag kinds. */
export const FLAG_LABEL: Record<string, string> = {
  out_of_focus: "Soft picture",
  overexposed: "Overexposed",
  underexposed: "Underexposed",
  black_frames: "Black frames",
  frozen_frames: "Frozen picture",
  long_silence: "Long silence",
  clipped_audio: "Clipped audio",
  low_audio_level: "Low audio level",
  audio_unreadable: "Audio not analysed",
};

const METRIC_LABEL: Record<string, string> = {
  blur: "blur measure",
  sharpness: "detail measure",
  luma_mean: "average brightness",
  clipped: "share of blown-out pixels",
  crushed: "share of pure-black pixels",
  clipped_pct: "% of samples at full scale",
  integrated_lufs: "loudness (LUFS)",
  seconds: "seconds",
};

export function flagLabel(kind: string): string {
  return FLAG_LABEL[kind] ?? kind.replaceAll("_", " ");
}

/** Score as editors read it: 0–100. */
export function scoreText(score: number | null | undefined): string {
  return score == null ? "–" : String(Math.round(score * 100));
}

/** Why a flag was raised: the measured value against its threshold, or the detector used. */
export function explainFlag(flag: Pick<QcFlagOut, "details">): string {
  const d = flag.details as {
    metric?: string;
    value?: number | null;
    threshold?: number;
    direction?: string;
    detector?: string;
    reason?: string;
  };
  if (d.reason) return d.reason;
  if (d.metric && d.threshold !== undefined) {
    const value = d.value == null ? "silent" : String(d.value);
    return `${METRIC_LABEL[d.metric] ?? d.metric} ${value}, limit ${d.direction === "below" ? "at least" : "at most"} ${d.threshold}`;
  }
  return d.detector ? `found by ${d.detector}` : "";
}
