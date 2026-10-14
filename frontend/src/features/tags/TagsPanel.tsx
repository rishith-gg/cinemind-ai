import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ShotTagsOut, TagOut } from "../../api";
import { listMediaTagsOptions, listMediaTagsQueryKey, reviewTagMutation } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { formatTime } from "../library/format";
import { hiddenReason, tagTitle } from "./labels";

interface Props {
  mediaId: string;
  time: number;
  onSeek: (seconds: number) => void;
}

type Decision = "approved" | "rejected" | "none";

function Chip({ tag, onReview, busy }: { tag: TagOut; onReview: (d: Decision) => void; busy: boolean }) {
  const score = tag.score == null ? "" : ` ${tag.score.toFixed(2)}`;
  return (
    <li className="flex items-center gap-1 rounded-full border border-neutral-700 bg-neutral-900 py-0.5 pl-2 pr-1 text-xs" title={tagTitle(tag)}>
      <span>
        {tag.label}
        <span className="text-neutral-400">{score}</span>
        {tag.review === "approved" && <span className="text-green-300"> · approved</span>}
      </span>
      {tag.review !== "approved" && (
        <button className="rounded px-1 text-green-300 hover:bg-neutral-800" disabled={busy} onClick={() => onReview("approved")} aria-label={`Approve ${tag.label}`}>
          ✓
        </button>
      )}
      <button className="rounded px-1 text-red-300 hover:bg-neutral-800" disabled={busy} onClick={() => onReview("rejected")} aria-label={`Reject ${tag.label}`}>
        ✕
      </button>
    </li>
  );
}

function ShotRow({ shot, current, calibrated, onSeek, review, busy }: { shot: ShotTagsOut; current: boolean; calibrated: boolean; onSeek: (s: number) => void; review: (shot: string, name: string, d: Decision) => void; busy: boolean }) {
  const shown = shot.tags.filter((t) => t.visible);
  const hidden = shot.tags.filter((t) => !t.visible && t.source === "model");
  return (
    <li className={`space-y-1 rounded p-2 ${current ? "bg-neutral-800/70" : ""}`} aria-current={current ? "true" : undefined}>
      <button className="font-mono text-xs text-blue-300" onClick={() => onSeek(shot.start_s)} aria-label={`Jump to shot ${shot.index + 1} at ${formatTime(shot.start_s)}`}>
        Shot {shot.index + 1} · {formatTime(shot.start_s)}
      </button>
      {shown.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Tags of shot ${shot.index + 1}`}>
          {shown.map((t) => (
            <Chip key={t.name} tag={t} busy={busy} onReview={(d) => review(shot.shot_id, t.name, d)} />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-neutral-500">{calibrated ? "No tag passed its evaluated threshold." : "No tags shown (no evaluated thresholds)."}</p>
      )}
      {hidden.length > 0 && (
        <details className="text-xs text-neutral-400">
          <summary className="cursor-pointer">{hidden.length} hidden suggestions</summary>
          <ul className="mt-1 space-y-0.5">
            {hidden.map((t) => (
              <li key={t.name} className="flex flex-wrap items-center gap-2" title={tagTitle(t)}>
                <span className={t.review === "rejected" ? "line-through" : ""}>
                  {t.label} {t.score == null ? "" : t.score.toFixed(2)}
                </span>
                <span className="text-neutral-500">{hiddenReason(t)}</span>
                {t.review === "rejected" ? (
                  <button className="text-blue-300 underline" disabled={busy} onClick={() => review(shot.shot_id, t.name, "none")}>
                    Undo reject
                  </button>
                ) : (
                  <button className="text-blue-300 underline" disabled={busy} onClick={() => review(shot.shot_id, t.name, "approved")} aria-label={`Approve ${t.label} anyway`}>
                    Approve anyway
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

/** Clip page: tag suggestions per shot. Only tags above a threshold that was evaluated on
 * labelled photos are shown; the rest are listed as hidden with the reason. The user's approve
 * and reject decisions outrank the threshold and are kept when the clip is processed again. */
export function TagsPanel({ mediaId, time, onSeek }: Props) {
  const qc = useQueryClient();
  const options = listMediaTagsOptions({ path: { media_id: mediaId } });
  const { data, error } = useQuery(options);
  const mutation = useMutation({
    ...reviewTagMutation(),
    onSuccess: (fresh) => qc.setQueryData(listMediaTagsQueryKey({ path: { media_id: mediaId } }), fresh),
  });
  if (error) return <p className="text-sm text-red-300">{errorMessage(error)}</p>;
  if (!data) return null;
  const review = (shot_id: string, name: string, decision: Decision) => mutation.mutate({ body: { shot_id, name, decision } });
  const anyModelTags = data.shots.some((s) => s.tags.some((t) => t.source === "model"));
  return (
    <section aria-label="Tags" className="space-y-2 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">Tags</h2>
        {data.model && <p className="text-xs text-neutral-400">{data.model} · suggestions, not facts</p>}
      </div>
      {data.message && (
        <p role="note" className="text-sm text-neutral-400">
          {data.message}
        </p>
      )}
      {anyModelTags && (
        <p className="text-xs text-neutral-400">
          {data.calibrated
            ? `A tag is shown when most of a shot's keyframes pass a threshold set on labelled public photos (${data.calibrated}); scores are shares within a group (0 to 1), not probabilities. Hover a tag for how often it was right on those photos.`
            : "No evaluated thresholds exist for this model, so no model tag is shown. Approve suggestions by hand if they fit."}
        </p>
      )}
      {data.shots.length > 0 && (
        <ol className="max-h-80 space-y-1 overflow-y-auto">
          {data.shots.map((shot) => (
            <ShotRow key={shot.shot_id} shot={shot} calibrated={!!data.calibrated} current={time >= shot.start_s && time < shot.end_s} onSeek={onSeek} review={review} busy={mutation.isPending} />
          ))}
        </ol>
      )}
    </section>
  );
}
