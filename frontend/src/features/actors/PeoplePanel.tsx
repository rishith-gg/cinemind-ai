import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { getMediaFacesOptions } from "../../api/@tanstack/react-query.gen";
import { formatTime } from "../library/format";
import { plural, why } from "./people";

/** Clip page: the people whose faces were found in this clip; a time jumps the player there. */
export function PeoplePanel({ mediaId, onSeek }: { mediaId: string; onSeek: (seconds: number) => void }) {
  const { data } = useQuery(getMediaFacesOptions({ path: { media_id: mediaId } }));
  if (!data) return null;
  const rejected = (data.details as { rejected?: Record<string, number> }).rejected ?? {};
  const left = Object.values(rejected).reduce((sum, n) => sum + n, 0);
  const tracks = data.tracks.filter((t) => t.actor_id);
  const aside = data.tracks.filter((t) => t.state === "ignored" || t.state === "unknown").length;
  const waiting = data.tracks.length - tracks.length - aside;
  return (
    <section aria-label="People" className="space-y-2">
      <h2 className="text-sm font-semibold">People</h2>
      {data.message && (
        <p role={data.status === "model_missing" ? "alert" : "status"} className="text-sm text-neutral-400">
          {data.message}
        </p>
      )}
      {data.status === "done" && (
        <p className="text-xs text-neutral-400" title={Object.entries(rejected).map(([k, n]) => `${k.replace("_", " ")}: ${n}`).join(", ")}>
          {plural(data.faces_used, "face")} used from {plural(data.frames_sampled, "sampled frame")}, up to {data.max_in_frame} in one frame
          {left > 0 && `; ${left} left out as too small, turned, blurred or uncertain`}
          {aside > 0 && `; ${plural(aside, "appearance")} set aside by you`}
          {waiting > 0 && `; ${plural(waiting, "appearance")} not grouped yet (grouping runs when processing is done)`}. Groups are
          suggestions.
        </p>
      )}
      {tracks.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {tracks.map((track) => (
            <li key={track.id} title={why(track)} className="w-20 text-xs">
              <img src={track.crop_url} alt={`Face of ${track.actor_name ?? "someone"}`} loading="lazy" className="aspect-square w-full rounded object-cover" />
              <Link className="block truncate underline" to={`/actors/${track.actor_id}`}>
                {track.actor_name}
              </Link>
              <button className="font-mono text-blue-300" onClick={() => onSeek(track.start_s)} aria-label={`Jump to ${track.actor_name} at ${formatTime(track.start_s)}`}>
                {formatTime(track.start_s)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
