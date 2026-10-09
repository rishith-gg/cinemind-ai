import { useQuery } from "@tanstack/react-query";

import { listMediaShotsOptions } from "../../api/@tanstack/react-query.gen";
import { formatTime } from "../library/format";

interface Props {
  mediaId: string;
  duration: number;
  time: number;
  onSeek: (seconds: number) => void;
}

/** The clip's detected shots as one bar, each as wide as it is long. Click a shot to jump to
 * its first frame. The caption says which detector and threshold produced the cuts. */
export function ShotStrip({ mediaId, duration, time, onSeek }: Props) {
  const { data, error } = useQuery(listMediaShotsOptions({ path: { media_id: mediaId } }));
  if (error) return <p className="text-xs text-red-300">The shot list could not be loaded.</p>;
  if (!data) return null;
  if (data.length === 0) return <p className="text-xs text-neutral-500">Shots have not been detected yet.</p>;
  const detection = (data[0]?.detection ?? {}) as { library?: string; detector?: string; threshold?: number };
  return (
    <div className="space-y-1">
      <ol aria-label="Shots" className="flex h-14 w-full gap-px overflow-hidden rounded bg-neutral-800">
        {data.map((shot) => {
          const current = time >= shot.start_s && time < shot.end_s;
          const key = shot.keyframes[0];
          return (
            <li
              key={shot.id}
              className="min-w-[3px]"
              style={{ flexGrow: Math.max(shot.end_s - shot.start_s, 0.001), flexBasis: 0 }}
            >
              <button
                type="button"
                aria-label={`Shot ${shot.index + 1}: ${formatTime(shot.start_s)} to ${formatTime(shot.end_s)}`}
                aria-current={current ? "true" : undefined}
                title={`Shot ${shot.index + 1} · ${formatTime(shot.start_s)} – ${formatTime(shot.end_s)}`}
                className={`relative h-full w-full overflow-hidden bg-neutral-900 bg-cover bg-center text-left ${current ? "outline-2 -outline-offset-2 outline-blue-500" : "opacity-80 hover:opacity-100"}`}
                style={key ? { backgroundImage: `url(/api/keyframes/${key.id}/image)` } : undefined}
                onClick={() => onSeek(shot.start_s)}
              >
                <span className="absolute bottom-0 left-0 bg-black/70 px-1 text-[10px]">{shot.index + 1}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-neutral-500">
        {data.length} {data.length === 1 ? "shot" : "shots"} over {formatTime(duration)}
        {detection.detector && ` · detected by ${detection.library ?? "PySceneDetect"} (${detection.detector}, threshold ${detection.threshold})`}
      </p>
    </div>
  );
}
