import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import type { ActorOut, ActorsOut } from "../../api";
import {
  listActorsOptions,
  listSetAsideFacesOptions,
  mergeActorsMutation,
  placeFaceTracksMutation,
  regroupActorsMutation,
} from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration } from "../library/format";
import { HONEST_NOTE, plural, useRefreshPeople } from "./people";

export function ActorsPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to see the people in its footage.
      </EmptyState>
    );
  }
  return <Actors projectId={projectId} />;
}

function ActorCard({ actor, selected, onToggle }: { actor: ActorOut; selected: boolean; onToggle: () => void }) {
  return (
    <li className={`rounded border bg-neutral-900 p-2 ${selected ? "border-blue-500" : "border-neutral-800"}`}>
      <Link to={`/actors/${actor.id}`} className="block">
        {actor.crop_url && <img src={actor.crop_url} alt={`Face of ${actor.name}`} loading="lazy" className="aspect-square w-full rounded object-cover" />}
        <span className={`mt-1 block truncate text-sm ${actor.named ? "font-medium" : "text-neutral-300"}`}>{actor.name}</span>
      </Link>
      <p className="text-xs text-neutral-400">
        {plural(actor.tracks, "appearance")} in {plural(actor.clips, "clip")} · {formatDuration(actor.seen_s)}
      </p>
      <label className="mt-1 flex items-center gap-1 text-xs text-neutral-400">
        <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${actor.name}`} />
        Select
      </label>
    </li>
  );
}

function SetAside({ projectId }: { projectId: string }) {
  const refresh = useRefreshPeople();
  const { data } = useQuery(listSetAsideFacesOptions({ path: { project_id: projectId } }));
  const restore = useMutation({ ...placeFaceTracksMutation(), onSuccess: refresh });
  if (!data?.length) return null;
  return (
    <section aria-label="Set aside" className="space-y-2">
      <h2 className="text-sm font-semibold">Set aside by you</h2>
      <ul className="flex flex-wrap gap-2">
        {data.map((track) => (
          <li key={track.id} className="w-24 text-xs text-neutral-400">
            <img src={track.crop_url} alt="" loading="lazy" className="aspect-square w-full rounded object-cover opacity-70" />
            <span className="block truncate">{track.state === "ignored" ? "Not a face" : "Unknown person"}</span>
            <button
              className="underline"
              aria-label={`Put back the face from ${track.filename}`}
              onClick={() => restore.mutate({ path: { project_id: projectId }, body: { track_ids: [track.id], state: "auto" } })}
            >
              Put back
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Summary({ data }: { data: ActorsOut }) {
  const run = (data.run ?? {}) as { engine?: string; method?: string; cluster_distance?: number; tracks?: number; corrections_not_found?: number };
  const searched = (data.scans.done ?? 0) + (data.scans.no_faces ?? 0);
  return (
    <p role="status" className="text-xs text-neutral-400">
      {plural(data.actors.length, "person", "people")} from {plural(run.tracks ?? 0, "appearance")}; {plural(data.scans.done ?? 0, "clip")} with
      usable faces out of {searched} searched.
      {run.method && ` Grouped with ${run.engine}, ${run.method}${run.cluster_distance === undefined ? "" : `, distance ${run.cluster_distance}`}.`}
      {!!run.corrections_not_found &&
        ` ${plural(run.corrections_not_found, "correction")} could not be matched to a face any more (kept in case the face returns).`}
    </p>
  );
}

function Actors({ projectId }: { projectId: string }) {
  const refresh = useRefreshPeople();
  const [selected, setSelected] = useState<string[]>([]);
  const { data, error, isPending, refetch } = useQuery(listActorsOptions({ path: { project_id: projectId } }));
  const merge = useMutation({
    ...mergeActorsMutation(),
    onSuccess: (actor) => {
      toast.success(`Merged into ${actor.name}.`);
      setSelected([]);
      refresh();
    },
  });
  const regroup = useMutation({
    ...regroupActorsMutation(),
    onSuccess: () => {
      toast.info("Grouped again. Your corrections were kept.");
      refresh();
    },
  });
  const toggle = (id: string) => setSelected((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  // Only people still on the page count: a refresh may have removed some of the selected.
  const chosen = (data?.actors ?? []).filter((a) => selected.includes(a.id));
  // The person who keeps their identity: a named one if there is one, else the most seen.
  const keep = chosen.find((a) => a.named) ?? chosen[0];

  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Actors</h1>
          <p className="max-w-3xl text-sm text-neutral-400">{HONEST_NOTE}</p>
        </div>
        {!!data?.run && (
          <button
            className="shrink-0 rounded bg-neutral-800 px-3 py-1.5 text-sm"
            disabled={regroup.isPending}
            onClick={() => regroup.mutate({ path: { project_id: projectId } })}
          >
            Group again
          </button>
        )}
      </div>
      {isPending && <Loading label="Loading people…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.message && (
        <p role="alert" className="rounded border border-amber-800 bg-amber-950 p-3 text-sm">
          {data.message}
        </p>
      )}
      {data && <Summary data={data} />}
      {data && data.actors.length === 0 && !data.message && (
        <EmptyState title="No people found">
          {Object.keys(data.scans).length === 0 ? (
            <>
              <Link className="underline" to="/library">
                Import footage
              </Link>{" "}
              to look for faces.
            </>
          ) : (
            "No usable face was found in this project's clips (faces must be large, sharp and roughly frontal)."
          )}
        </EmptyState>
      )}
      {chosen.length >= 2 && keep && (
        <div role="region" aria-label="Merge" className="flex flex-wrap items-center gap-3 rounded border border-blue-800 bg-blue-950/40 p-2 text-sm">
          <span>
            {chosen.length} selected: {chosen.map((a) => a.name).join(", ")}
          </span>
          <button
            className="rounded bg-blue-600 px-3 py-1"
            disabled={merge.isPending}
            onClick={() => merge.mutate({ path: { actor_id: keep.id }, body: { actor_ids: chosen.filter((a) => a.id !== keep.id).map((a) => a.id) } })}
          >
            Merge into {keep.name}
          </button>
          <button className="underline" onClick={() => setSelected([])}>
            Clear
          </button>
        </div>
      )}
      {data && data.actors.length > 0 && (
        <ul aria-label="People" className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {data.actors.map((actor) => (
            <ActorCard key={actor.id} actor={actor} selected={selected.includes(actor.id)} onToggle={() => toggle(actor.id)} />
          ))}
        </ul>
      )}
      <SetAside projectId={projectId} />
    </section>
  );
}
