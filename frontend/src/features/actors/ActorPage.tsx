import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import type { ActorDetail } from "../../api";
import {
  getActorOptions,
  listActorsOptions,
  placeFaceTracksMutation,
  renameActorMutation,
  splitActorMutation,
} from "../../api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "../../components/states";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration, formatTime } from "../library/format";
import { decidedBy, plural, useRefreshPeople, why } from "./people";

export function ActorPage() {
  const { actorId = "" } = useParams();
  const { data, error, isPending, refetch } = useQuery(getActorOptions({ path: { actor_id: actorId } }));
  if (isPending) return <Loading label="Loading person…" />;
  if (error || !data) {
    return (
      <div className="space-y-3">
        <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />
        <Link className="text-sm underline" to="/actors">
          Back to actors
        </Link>
      </div>
    );
  }
  return <Person key={data.id} actor={data} />;
}

function RenameForm({ actor }: { actor: ActorDetail }) {
  const refresh = useRefreshPeople();
  const [name, setName] = useState(actor.name);
  const rename = useMutation({
    ...renameActorMutation(),
    onSuccess: (saved) => {
      toast.success(`Named ${saved.name}.`);
      setName(saved.name);
      refresh();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) rename.mutate({ path: { actor_id: actor.id }, body: { name } });
  };
  return (
    <form className="flex gap-2" onSubmit={submit}>
      <input
        aria-label="Name"
        maxLength={100}
        className="w-64 rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button className="rounded bg-blue-600 px-3 py-1.5 text-sm" disabled={rename.isPending || !name.trim() || name === actor.name}>
        Save name
      </button>
    </form>
  );
}

function Person({ actor }: { actor: ActorDetail }) {
  // The person's own project, whichever project is selected in the header.
  const projectId = actor.project_id;
  const refresh = useRefreshPeople();
  const navigate = useNavigate();
  const [picked, setSelected] = useState<string[]>([]);
  const [wanted, setTarget] = useState("");
  const others = useQuery(listActorsOptions({ path: { project_id: projectId } }));
  // The page refreshes while jobs run: only what is still shown counts as selected.
  const selected = picked.filter((id) => actor.track_list.some((t) => t.id === id));
  const done = (message: string, leave = false) => {
    toast.success(message);
    setSelected([]);
    refresh();
    // Nothing of this person is left on the page: go back to the list.
    if (leave) void navigate("/actors");
  };
  const all = selected.length > 0 && selected.length === actor.track_list.length;
  const split = useMutation({ ...splitActorMutation(), onSuccess: (created) => done(`Moved to a new person: ${created.name}.`) });
  const place = useMutation({ ...placeFaceTracksMutation(), onSuccess: () => done("Done. Grouping again will keep this.", all) });
  const send = (state: "actor" | "ignored" | "unknown", actor_id?: string) =>
    place.mutate({ path: { project_id: projectId }, body: { track_ids: selected, state, actor_id } });
  const toggle = (id: string) => setSelected((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  const busy = split.isPending || place.isPending;
  const choices = (others.data?.actors ?? []).filter((a) => a.id !== actor.id);
  const target = choices.some((a) => a.id === wanted) ? wanted : "";

  return (
    <section className="space-y-4">
      <div>
        <Link className="text-sm text-neutral-400 underline" to="/actors">
          ← Actors
        </Link>
        <h1 className="text-xl font-semibold">{actor.name}</h1>
        <p className="text-sm text-neutral-400">
          {plural(actor.tracks, "appearance")} in {plural(actor.clips, "clip")}, {formatDuration(actor.seen_s)} on screen (where a usable face
          was seen). An appearance is one face followed through one shot.
        </p>
      </div>
      <RenameForm actor={actor} />
      <div role="region" aria-label="Corrections" className="flex flex-wrap items-center gap-2 rounded border border-neutral-800 p-2 text-sm">
        <span className="text-neutral-400">{selected.length ? `${selected.length} selected:` : "Select appearances that do not belong here, then:"}</span>
        <button
          className="rounded bg-neutral-800 px-2 py-1 disabled:opacity-40"
          disabled={busy || !selected.length || all}
          title={all ? "Leave at least one appearance with this person" : undefined}
          onClick={() => split.mutate({ path: { actor_id: actor.id }, body: { track_ids: selected } })}
        >
          Split into a new person
        </button>
        <select aria-label="Move to" className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Move to…</option>
          {choices.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <button className="rounded bg-neutral-800 px-2 py-1 disabled:opacity-40" disabled={busy || !selected.length || !target} onClick={() => send("actor", target)}>
          Move
        </button>
        <button className="rounded bg-neutral-800 px-2 py-1 disabled:opacity-40" disabled={busy || !selected.length} onClick={() => send("ignored")}>
          Not a face
        </button>
        <button className="rounded bg-neutral-800 px-2 py-1 disabled:opacity-40" disabled={busy || !selected.length} onClick={() => send("unknown")}>
          Unknown person
        </button>
        <button className="ml-auto underline" onClick={() => setSelected(all ? [] : actor.track_list.map((t) => t.id))}>
          {all ? "Select none" : "Select all"}
        </button>
      </div>
      <ul aria-label="Appearances" className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
        {actor.track_list.map((track) => {
          const on = selected.includes(track.id);
          return (
            <li key={track.id} title={why(track)} className={`rounded border bg-neutral-900 p-2 text-xs ${on ? "border-blue-500" : "border-neutral-800"}`}>
              <label className="block cursor-pointer">
                <img src={track.crop_url} alt={`Face in ${track.filename} at ${formatTime(track.start_s)}`} loading="lazy" className="aspect-square w-full rounded object-cover" />
                <span className="mt-1 flex items-center gap-1 text-neutral-400">
                  <input type="checkbox" checked={on} onChange={() => toggle(track.id)} aria-label={`Select the appearance in ${track.filename} at ${formatTime(track.start_s)}`} />
                  {decidedBy(track)}
                </span>
              </label>
              <Link className="block truncate underline" to={`/library/${track.media_id}?t=${track.start_s}`}>
                {track.filename}
              </Link>
              <span className="font-mono text-neutral-400">
                {formatTime(track.start_s)}–{formatTime(track.end_s)}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
