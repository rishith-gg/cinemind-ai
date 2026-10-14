import { useQueryClient } from "@tanstack/react-query";

import type { FaceTrackOut } from "../../api";

// Queries that show faces or people; every correction changes what they return.
export const PEOPLE_QUERIES = new Set(["listActors", "getActor", "listSetAsideFaces", "getMediaFaces", "listActorPairs"]);

export function useRefreshPeople(): () => void {
  const qc = useQueryClient();
  return () =>
    void qc.invalidateQueries({
      predicate: (q) => {
        const id = (q.queryKey[0] as { _id?: string } | undefined)?._id;
        return !!id && PEOPLE_QUERIES.has(id);
      },
    });
}

export const HONEST_NOTE =
  "People are grouped by how alike their faces look to a small local model. Groups can be wrong: one person may be split " +
  "over several, or two people put together. Names are yours and stay in this project; nothing is matched to real identities.";

/** Why a face sits where it does, for the tooltip. */
export function why(track: FaceTrackOut): string {
  const a = track.assignment as { how?: string; similarity_to_group?: number; method?: string; cluster_distance?: number };
  if (!a.how) return "";
  const parts = [a.how];
  if (typeof a.similarity_to_group === "number") parts.push(`similarity to the group ${a.similarity_to_group.toFixed(2)}`);
  if (a.method) parts.push(typeof a.cluster_distance === "number" ? `${a.method}, distance ${a.cluster_distance}` : a.method);
  return parts.join(" · ");
}

/** Short label under a face: who decided where it sits. */
export function decidedBy(track: FaceTrackOut): string {
  if (track.state !== "pinned") return "by similarity";
  return (track.assignment as { how?: string }).how === "placed by you" ? "placed by you" : "kept by your correction";
}

export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;
