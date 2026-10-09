import { Link } from "react-router";

import type { MediaOut } from "../../api";
import { QualityBadge } from "../quality/QualityBadge";
import { formatBytes, formatDuration, mediaStatus, STATUS_LABEL, type Status } from "./format";

const STATUS_STYLE: Record<Status, string> = {
  ready: "bg-green-900/60 text-green-300",
  processing: "bg-blue-900/60 text-blue-300",
  queued: "bg-neutral-800 text-neutral-300",
  failed: "bg-red-900/60 text-red-300",
  missing: "bg-amber-900/60 text-amber-300",
};

export function StatusBadge({ media }: { media: MediaOut }) {
  const status = mediaStatus(media);
  const pct = status === "processing" && media.job ? ` ${Math.round(media.job.progress * 100)}%` : "";
  return <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`}>{STATUS_LABEL[status] + pct}</span>;
}

export function MediaCard({ media }: { media: MediaOut }) {
  const failed = mediaStatus(media) === "failed";
  return (
    <li className="overflow-hidden rounded border border-neutral-800 bg-neutral-900">
      <Link to={`/library/${media.id}`} className="block hover:bg-neutral-800/60" aria-label={`Open ${media.filename}`} aria-describedby={`quality-${media.id}`}>
        <div className="flex aspect-video items-center justify-center bg-black text-xs text-neutral-500">
          {media.has_poster ? (
            <img src={`/api/media/${media.id}/poster`} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <span>{media.probed && !media.width ? "Audio only" : "No thumbnail yet"}</span>
          )}
        </div>
        <div className="space-y-1 p-3">
          <p className="truncate text-sm font-medium" title={media.filename}>
            {media.filename}
          </p>
          <p className="text-xs text-neutral-400">
            {formatDuration(media.duration_s)} · {media.width ? `${media.width}×${media.height}` : "–"} ·{" "}
            {formatBytes(media.size_bytes)}
          </p>
          <div className="flex flex-wrap items-center gap-1">
            <StatusBadge media={media} />
            <QualityBadge media={media} id={`quality-${media.id}`} />
          </div>
          {failed && media.job?.error_message && <p className="text-xs text-red-300">{media.job.error_message}</p>}
        </div>
      </Link>
    </li>
  );
}
