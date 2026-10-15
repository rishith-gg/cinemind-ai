import { Link } from "react-router";

import type { MarkOut, SearchResult } from "../../api";
import { formatTime } from "../library/format";
import { MarkButtons } from "../marks/MarkButtons";
import { SIGNAL_LABEL, whyLine } from "./labels";

interface Props {
  result: SearchResult;
  position: number; // 1-based place in the ranked list
  describe: (shotId: string) => string; // "walk.mov shot 3", for the duplicate note
  onMoreLike: (shotId: string) => void;
  onMarked: (out: MarkOut) => void;
  onJudge?: (shotId: string, relevant: boolean | null) => void;
}

const sign = (n: number) => (n < 0 ? `−${Math.abs(n).toFixed(2)}` : `+${n.toFixed(2)}`);

function Breakdown({ result, describe }: { result: SearchResult; describe: (shotId: string) => string }) {
  const rows = Object.entries(result.breakdown).filter(([, s]) => s.weight > 0);
  return (
    <table className="w-full text-xs text-neutral-400" aria-label="Score breakdown">
      <tbody>
        {rows.map(([name, s]) => (
          <tr key={name}>
            <td className="pr-1">{SIGNAL_LABEL[name] ?? name}</td>
            <td className="text-right font-mono">
              {s.value.toFixed(2)} × {s.weight.toFixed(1)}
            </td>
            <td className={`w-12 text-right font-mono ${s.contribution < 0 ? "text-red-300" : "text-neutral-200"}`}>{sign(s.contribution)}</td>
          </tr>
        ))}
        <tr className="border-t border-neutral-800">
          <td className="pr-1 text-neutral-200">Score</td>
          <td />
          <td className="text-right font-mono text-neutral-100">{result.final.toFixed(2)}</td>
        </tr>
      </tbody>
      {(result.duplicate_of || result.notes.length > 0) && (
        <caption className="caption-bottom pt-0.5 text-left">
          {result.duplicate_of && `Looks like ${describe(result.duplicate_of)}, placed higher. `}
          {result.notes.join("; ")}
        </caption>
      )}
    </table>
  );
}

/** One search result: picture, clip, time, what matched and why it ranks here. */
export function ResultCard({ result, position, describe, onMoreLike, onMarked, onJudge }: Props) {
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
          <span className="font-mono text-neutral-500">#{position}</span> {result.filename} · shot {result.shot_index + 1} · <span className="font-mono">{formatTime(result.jump_s)}</span>
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
      <Breakdown result={result} describe={describe} />
      <details className="text-xs text-neutral-400">
        <summary className="cursor-pointer">Found by {Object.keys(result.why).length} of the result lists</summary>
        <ul aria-label="Why this result" className="space-y-0.5">
          {Object.entries(result.why).map(([name, hit]) => (
            <li key={name}>{whyLine(name, hit)}</li>
          ))}
        </ul>
      </details>
      <MarkButtons shotId={result.shot_id} label={`${result.filename} shot ${result.shot_index + 1}`} mark={result.mark} stars={result.stars} onChanged={onMarked} />
      {result.mark === "reject" && <p className="text-xs text-red-300">Rejected: left out of search unless “Show rejected” is on.</p>}
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
