import type { MediaOut } from "../../api";
import { formatBytes, formatDuration, formatFps } from "./format";

export function MetadataPanel({ media }: { media: MediaOut }) {
  const rows: [string, string][] = [
    ["File", media.filename],
    ["Stored as", media.import_mode === "reference" ? `Referenced in place: ${media.path}` : `${media.import_mode} (copy in project data)`],
    ["Container", media.container ?? "–"],
    ["Duration", formatDuration(media.duration_s)],
    ["Resolution", media.width ? `${media.width}×${media.height}` : "audio only"],
    ["Frame rate", formatFps(media)],
    ["Video codec", media.video_codec ?? "–"],
    ["Audio", media.audio_codec ? `${media.audio_codec}, ${media.audio_channels ?? "?"} ch, ${media.audio_sample_rate ?? "?"} Hz` : "none"],
    ["Bitrate", media.bit_rate ? `${(media.bit_rate / 1e6).toFixed(1)} Mb/s` : "–"],
    ["Timecode start", media.start_timecode ?? "–"],
    ["Size", formatBytes(media.size_bytes)],
    ["Colour", Object.values(media.color).join(", ") || "–"],
    ["Proxy encoder", media.proxy_encoder ?? "–"],
  ];
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-neutral-400">{k}</dt>
          <dd className="break-all">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
