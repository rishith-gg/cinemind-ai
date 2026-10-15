import { Link } from "react-router";

import type { SearchResult } from "../../api";
import { formatTime } from "../library/format";
import { whyLine } from "./labels";

interface Props {
  result: SearchResult;
  onMoreLike: (shotId: string) => void;
  onJudge?: (shotId: string, relevant: boolean | null) => void;
}

/** One search result: picture, clip, time, what matched and why it ranks here. */
export function ResultCard({ result, onMoreLike, onJudge }: Props) {
  const spoken = result.why.keyword ?? result.why.text;
  const parts = spoken?.parts ?? (spoken?.text ? [{ text: spoken.text, match: false }] : []);
  return (
    <li className={`space-y-1 rounded border bg-neutral-900 p-2 text-sm ${result.relevant === true ? "border-green-700" : result.relevant === false ? "border-red-900" : "border-neutral-800"}`}>
      <Link to={`/library/${result.media_id}?t=${result.jump_s}`} className="block" aria-label={`Open ${result.filename} at ${formatTime(result.jump_s)}`}>
        {result.keyframe_url ? (
          <img src={result.keyframe_url} alt="" loading="lazy" className="aspect-video w-full rounded object-cover" />
        ) : (
          <div className="aspect-video w-full rounded bg-neutral-800" />
        )}
        <span className="mt-1 block truncate text-xs text-neutral-300">
          {result.filename} · shot {result.shot_index + 1} · <span className="font-mono">{formatTime(result.jump_s)}</span>
        </span>
      </Link>
      {parts.length > 0 && (
        <p className="text-xs">
          “
          {parts.map((p, i) =>
            p.match ? (
              <mark key={i} className="rounded bg-yellow-500/80 px-0.5 text-black">
                {p.text}
              </mark>
            ) : (
              <span key={i}>{p.text}</span>
            ),
          )}
          ”
        </p>
      )}
      <ul aria-label="Why this result" className="space-y-0.5 text-xs text-neutral-400">
        {Object.entries(result.why).map(([name, hit]) => (
          <li key={name}>{whyLine(name, hit)}</li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button className="text-blue-300 underline" onClick={() => onMoreLike(result.shot_id)}>
          More like this
        </button>
        {onJudge && (
          <span className="ml-auto flex items-center gap-1">
            <button
              aria-label={`Good result: ${result.filename} shot ${result.shot_index + 1}`}
              aria-pressed={result.relevant === true}
              className={`rounded px-1.5 ${result.relevant === true ? "bg-green-700 text-white" : "bg-neutral-800 text-green-300"}`}
              onClick={() => onJudge(result.shot_id, result.relevant === true ? null : true)}
            >
              ✓
            </button>
            <button
              aria-label={`Not a good result: ${result.filename} shot ${result.shot_index + 1}`}
              aria-pressed={result.relevant === false}
              className={`rounded px-1.5 ${result.relevant === false ? "bg-red-800 text-white" : "bg-neutral-800 text-red-300"}`}
              onClick={() => onJudge(result.shot_id, result.relevant === false ? null : false)}
            >
              ✕
            </button>
          </span>
        )}
      </div>
    </li>
  );
}
