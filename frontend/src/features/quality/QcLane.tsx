import { useQuery } from "@tanstack/react-query";

import { getMediaQualityOptions } from "../../api/@tanstack/react-query.gen";
import { formatTime } from "../library/format";
import { explainFlag, flagLabel } from "./labels";

/** QC flags on the clip's time axis (same width as the shot strip and waveform): one row per
 * kind of flag, so flags over the same range never cover each other. Click one to jump to it.
 * The reason for each flag is listed in the quality panel. */
export function QcLane({ mediaId, duration, onSeek }: { mediaId: string; duration: number; onSeek: (seconds: number) => void }) {
  const { data } = useQuery(getMediaQualityOptions({ path: { media_id: mediaId } }));
  if (!data || data.flags.length === 0 || duration <= 0) return null;
  const kinds = [...new Set(data.flags.map((f) => f.kind))];
  return (
    <div aria-label="QC flags" role="group" className="space-y-1">
      {kinds.map((kind) => (
        <div key={kind} className="flex items-center gap-2">
          <span className="w-32 shrink-0 truncate text-xs text-neutral-400">{flagLabel(kind)}</span>
          <ol className="relative h-4 min-w-0 flex-1 rounded bg-neutral-900">
            {data.flags
              .filter((f) => f.kind === kind)
              .map((flag, i) => {
                const left = Math.min(99, (flag.start_s / duration) * 100);
                const width = Math.max(1.5, ((flag.end_s - flag.start_s) / duration) * 100);
                const text = `${flagLabel(kind)}: ${formatTime(flag.start_s)} to ${formatTime(flag.end_s)}`;
                return (
                  <li key={`${flag.start_s}-${i}`}>
                    <button
                      type="button"
                      aria-label={text}
                      title={`${text} · ${explainFlag(flag)}`}
                      className={`absolute inset-y-0.5 rounded-sm opacity-80 hover:opacity-100 ${flag.source === "audio" ? "bg-fuchsia-500" : "bg-amber-500"}`}
                      style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                      onClick={() => onSeek(flag.start_s)}
                    />
                  </li>
                );
              })}
          </ol>
        </div>
      ))}
      <p className="text-xs text-neutral-500">QC flags on the clip’s time axis. Click one to jump there.</p>
    </div>
  );
}
