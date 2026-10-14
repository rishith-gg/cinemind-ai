import { create } from "zustand";

import type { MediaOut } from "../../api";

export const FILTERS = {
  all: { label: "All clips", keep: () => true },
  flagged: { label: "With QC flags", keep: (m: MediaOut) => m.qc_flags.length > 0 },
  low: { label: "Low technical score", keep: (m: MediaOut) => m.low_quality },
  clean: { label: "Scored, no QC flags", keep: (m: MediaOut) => m.quality_score != null && !m.low_quality && m.qc_flags.length === 0 },
} as const;
export const SORTS = {
  newest: { label: "Newest first", compare: () => 0 },
  worst: { label: "Technical score: lowest first", compare: (a: MediaOut, b: MediaOut) => (a.quality_score ?? 2) - (b.quality_score ?? 2) },
  best: { label: "Technical score: highest first", compare: (a: MediaOut, b: MediaOut) => (b.quality_score ?? -1) - (a.quality_score ?? -1) },
  name: { label: "Name", compare: (a: MediaOut, b: MediaOut) => a.filename.localeCompare(b.filename, undefined, { numeric: true }) },
} as const;
export type FilterKey = keyof typeof FILTERS;
export type SortKey = keyof typeof SORTS;

interface LibraryView {
  filter: FilterKey;
  sort: SortKey;
  setFilter: (filter: FilterKey) => void;
  setSort: (sort: SortKey) => void;
}

/** The library's filter and sort, shared with the clip page so Previous / Next follow the
 * order the user is looking at. */
export const useLibraryView = create<LibraryView>((set) => ({
  filter: "all",
  sort: "newest",
  setFilter: (filter) => set({ filter }),
  setSort: (sort) => set({ sort }),
}));

export function shownClips(clips: MediaOut[], filter: FilterKey, sort: SortKey): MediaOut[] {
  return clips.filter(FILTERS[filter].keep).sort(SORTS[sort].compare);
}

export interface Neighbours {
  previous: MediaOut | null;
  next: MediaOut | null;
  position: number; // 1-based
  total: number;
  filtered: boolean; // false when the clip is outside the filter and all clips are used
}

/** The clips before and after `id` in the library's order. A clip the filter hides (opened
 * from elsewhere) is placed among all clips instead, so it always has neighbours. */
export function neighbours(clips: MediaOut[], id: string, filter: FilterKey, sort: SortKey): Neighbours | null {
  let list = shownClips(clips, filter, sort);
  let filtered = filter !== "all";
  let at = list.findIndex((m) => m.id === id);
  if (at < 0) {
    list = shownClips(clips, "all", sort);
    filtered = false;
    at = list.findIndex((m) => m.id === id);
  }
  if (at < 0) return null;
  return { previous: list[at - 1] ?? null, next: list[at + 1] ?? null, position: at + 1, total: list.length, filtered };
}
