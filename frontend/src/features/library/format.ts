import type { MediaOut } from "../../api";

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Position inside a clip with hundredths, e.g. "0:03.52". */
export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${m}:${(seconds - m * 60).toFixed(2).padStart(5, "0")}`;
}

/** A rational frame rate as editors write it: 30000/1001 -> "29.97", 25/1 -> "25". */
export function rateLabel(num: number, den: number): string {
  return den === 1 ? `${num}` : (num / den).toFixed(3).replace(/0+$/, "");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

/** Frame rate as the exact rational plus a readable decimal, e.g. "30000/1001 (29.97)". */
export function formatFps(m: Pick<MediaOut, "fps_num" | "fps_den" | "is_vfr">): string {
  if (!m.fps_num || !m.fps_den) return "–";
  const dec = (m.fps_num / m.fps_den).toFixed(2).replace(/\.?0+$/, "");
  const text = m.fps_den === 1 ? `${m.fps_num}` : `${m.fps_num}/${m.fps_den} (${dec})`;
  return m.is_vfr ? `${text}, variable` : text;
}

export type Status = "ready" | "processing" | "queued" | "failed" | "missing";

export function mediaStatus(m: MediaOut): Status {
  if (m.job?.status === "failed" || m.job?.status === "cancelled") return "failed";
  if (m.job?.status === "running") return "processing";
  if (m.job?.status === "queued") return "queued";
  if (m.source_missing && !m.has_proxy) return "missing";
  return m.has_proxy ? "ready" : "queued";
}

export const STATUS_LABEL: Record<Status, string> = {
  ready: "Ready",
  processing: "Processing",
  queued: "Queued",
  failed: "Failed",
  missing: "Source missing",
};
