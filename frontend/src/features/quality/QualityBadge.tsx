import type { MediaOut } from "../../api";
import { flagLabel, scoreText } from "./labels";

/** Technical score (0–100) and the kinds of QC flags on a clip. `id` lets a card point its
 * description at this text, so the score and flags are read out with the card. */
export function QualityBadge({ media, id }: { media: Pick<MediaOut, "quality_score" | "low_quality" | "qc_flags">; id?: string }) {
  if (media.quality_score == null && media.qc_flags.length === 0) return null;
  return (
    <span id={id} className="flex flex-wrap items-center gap-1">
      {media.quality_score != null && (
        <span
          title="Technical score, 0–100: focus, exposure, contrast and audio level. Not a judgement of the shot."
          className={`rounded px-2 py-0.5 text-xs ${media.low_quality ? "bg-red-900/60 text-red-300" : "bg-neutral-800 text-neutral-300"}`}
        >
          Tech score {scoreText(media.quality_score)}
          {media.low_quality && " · low"}
        </span>
      )}
      {media.qc_flags.map((kind) => (
        <span key={kind} className="rounded bg-amber-900/50 px-2 py-0.5 text-xs text-amber-300">
          {flagLabel(kind)}
        </span>
      ))}
    </span>
  );
}
