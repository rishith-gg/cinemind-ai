import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { ActorOut } from "../../api";
import { answerActorPairMutation, listActorPairsOptions } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration } from "../library/format";
import { plural, useRefreshPeople } from "./people";

function Face({ actor }: { actor: ActorOut }) {
  return (
    <figure className="w-36 text-xs text-neutral-400">
      {actor.crop_url && <img src={actor.crop_url} alt={`Face of ${actor.name}`} className="aspect-square w-full rounded object-cover" />}
      <figcaption className="mt-1">
        <span className="block truncate text-sm text-neutral-200">{actor.name}</span>
        {plural(actor.clips, "clip")} · {formatDuration(actor.seen_s)}
      </figcaption>
    </figure>
  );
}

/** "Same person?" questions about the people whose faces look most alike. Yes merges them, no
 * keeps them apart in every later grouping; both answers are kept as labels for measuring where
 * the grouping limit should sit (eval/actor_pairs.py). */
export function PairReview({ projectId }: { projectId: string }) {
  const refresh = useRefreshPeople();
  const [skipped, setSkipped] = useState<string[]>([]);
  const { data } = useQuery(listActorPairsOptions({ path: { project_id: projectId } }));
  const answer = useMutation({
    ...answerActorPairMutation(),
    onSuccess: (_fresh, vars) => {
      toast.info(vars.body.same ? "Merged." : "Kept apart from now on.");
      refresh();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  if (!data) return null;
  const key = (a: string, b: string) => `${a}|${b}`;
  const open = data.pairs.filter((p) => !skipped.includes(key(p.first.id, p.second.id)));
  const pair = open[0];
  if (!pair && data.answered === 0) return null;
  const send = (same: boolean) => pair && answer.mutate({ path: { project_id: projectId }, body: { first_id: pair.first.id, second_id: pair.second.id, same } });
  return (
    <section aria-label="Same person?" className="space-y-2 rounded border border-neutral-800 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Same person?</h2>
        <p className="text-xs text-neutral-400">
          {plural(data.answered, "answer")} so far ({data.answered_same} same). Your answers also measure how well the grouping works.
        </p>
      </div>
      {pair ? (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <Face actor={pair.first} />
            <Face actor={pair.second} />
            <p className="max-w-xs text-xs text-neutral-400">
              Face distance {pair.distance.toFixed(2)}
              {data.cluster_distance != null && ` (grouped together below ${data.cluster_distance})`}. Most alike pairs come first; people seen in the same frame
              are never asked.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-sm">
            <button className="rounded bg-blue-600 px-3 py-1" disabled={answer.isPending} onClick={() => send(true)}>
              Same person
            </button>
            <button className="rounded bg-neutral-800 px-3 py-1" disabled={answer.isPending} onClick={() => send(false)}>
              Different people
            </button>
            <button className="underline" onClick={() => setSkipped((s) => [...s, key(pair.first.id, pair.second.id)])}>
              Not sure, skip
            </button>
          </div>
        </>
      ) : (
        <p className="text-sm text-neutral-400">No more questions right now.</p>
      )}
    </section>
  );
}
