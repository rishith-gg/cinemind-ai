import { useMutation } from "@tanstack/react-query";

import type { MarkOut } from "../../api";
import { markShotMutation } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";

interface Props {
  shotId: string;
  label: string; // e.g. "walk.mov shot 3", for screen readers
  mark: MarkOut["mark"];
  stars: number;
  onChanged: (out: MarkOut) => void;
}

/** Select / reject a shot and give it 0 to 5 stars. Rejected shots are left out of search;
 * selected and starred ones rank higher (the selection signal). */
export function MarkButtons({ shotId, label, mark, stars, onChanged }: Props) {
  const save = useMutation({
    ...markShotMutation(),
    onSuccess: onChanged,
    onError: (err) => toast.error(errorMessage(err)),
  });
  // Each button sends only what it changes, so a quick second click cannot undo the first.
  const setMark = (next: "select" | "reject" | "none") => save.mutate({ path: { shot_id: shotId }, body: { mark: next } });
  const setStars = (n: number) => save.mutate({ path: { shot_id: shotId }, body: { stars: n } });
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs" role="group" aria-label={`Marks for ${label}`}>
      <button
        aria-pressed={mark === "select"}
        aria-label={`Select ${label}`}
        disabled={save.isPending}
        className={`rounded px-1.5 py-0.5 ${mark === "select" ? "bg-green-700 text-white" : "bg-neutral-800 text-green-300"}`}
        onClick={() => setMark(mark === "select" ? "none" : "select")}
      >
        Select
      </button>
      <button
        aria-pressed={mark === "reject"}
        aria-label={`Reject ${label}`}
        disabled={save.isPending}
        className={`rounded px-1.5 py-0.5 ${mark === "reject" ? "bg-red-800 text-white" : "bg-neutral-800 text-red-300"}`}
        onClick={() => setMark(mark === "reject" ? "none" : "reject")}
      >
        Reject
      </button>
      <span className="ml-1" aria-label={`Stars for ${label}: ${stars} of 5`}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            aria-label={`${n} ${n === 1 ? "star" : "stars"} for ${label}`}
            aria-pressed={stars >= n}
            disabled={save.isPending}
            className={stars >= n ? "text-yellow-400" : "text-neutral-600"}
            onClick={() => setStars(stars === n ? 0 : n)}
          >
            ★
          </button>
        ))}
      </span>
    </div>
  );
}
