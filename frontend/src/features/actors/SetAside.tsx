import { useMutation, useQuery } from "@tanstack/react-query";

import type { ActorOut, FaceTrackOut } from "../../api";
import { listSetAsideFacesOptions, placeFaceTracksMutation } from "../../api/@tanstack/react-query.gen";
import { plural, useRefreshPeople, why } from "./people";

const LABEL: Record<string, string> = { ignored: "Not a face", unknown: "Unknown person", brief: "Seen briefly" };

function Item({ track, people, onPlace }: { track: FaceTrackOut; people: ActorOut[]; onPlace: (state: "auto" | "ignored" | "actor", actorId?: string) => void }) {
  const brief = track.state === "brief";
  return (
    <li className="w-28 space-y-0.5 text-xs text-neutral-400" title={why(track)}>
      <img src={track.crop_url} alt={`Face from ${track.filename}`} loading="lazy" className="aspect-square w-full rounded object-cover opacity-70" />
      <span className="block truncate">{LABEL[track.state] ?? track.state}</span>
      {brief ? (
        <>
          <button className="underline" aria-label={`Not a face: ${track.filename}`} onClick={() => onPlace("ignored")}>
            Not a face
          </button>
          {people.length > 0 && (
            <select
              className="w-full rounded border border-neutral-700 bg-neutral-900"
              aria-label={`Add the face from ${track.filename} to a person`}
              value=""
              onChange={(e) => e.target.value && onPlace("actor", e.target.value)}
            >
              <option value="">Add to…</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </>
      ) : (
        <button className="underline" aria-label={`Put back the face from ${track.filename}`} onClick={() => onPlace("auto")}>
          Put back
        </button>
      )}
    </li>
  );
}

/** Faces with no person: set aside by the user, or automatically because they were on screen
 * for a single sampled frame (shirts, raincoats and motion blur usually end up here). */
export function SetAside({ projectId, people }: { projectId: string; people: ActorOut[] }) {
  const refresh = useRefreshPeople();
  const { data } = useQuery(listSetAsideFacesOptions({ path: { project_id: projectId } }));
  const place = useMutation({ ...placeFaceTracksMutation(), onSuccess: refresh });
  if (!data?.length) return null;
  const mine = data.filter((t) => t.state !== "brief");
  const brief = data.filter((t) => t.state === "brief");
  const send = (track: FaceTrackOut) => (state: "auto" | "ignored" | "actor", actor_id?: string) =>
    place.mutate({ path: { project_id: projectId }, body: { track_ids: [track.id], state, actor_id } });
  return (
    <>
      {mine.length > 0 && (
        <section aria-label="Set aside" className="space-y-2">
          <h2 className="text-sm font-semibold">Set aside by you</h2>
          <ul className="flex flex-wrap gap-2">
            {mine.map((t) => (
              <Item key={t.id} track={t} people={people} onPlace={send(t)} />
            ))}
          </ul>
        </section>
      )}
      {brief.length > 0 && (
        <details aria-label="Seen briefly" className="space-y-2">
          <summary className="cursor-pointer text-sm font-semibold">
            Seen briefly: {plural(brief.length, "face")} set aside automatically
          </summary>
          <p className="text-xs text-neutral-400">
            Found in a single sampled frame, so not grouped into people (most are clothing, masks or motion blur). Add a real one to its person.
          </p>
          <ul className="flex flex-wrap gap-2">
            {brief.map((t) => (
              <Item key={t.id} track={t} people={people} onPlace={send(t)} />
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
