import { useQuery } from "@tanstack/react-query";

import { listActorsOptions, listMediaOptions, listScenesOptions } from "../../api/@tanstack/react-query.gen";

export interface FilterValues {
  media_id?: string;
  actor_id?: string;
  scene_id?: string;
  min_quality?: number;
  has_dialogue: boolean;
  selects_only: boolean;
  include_rejected: boolean;
}

const SELECT = "rounded border border-neutral-700 bg-neutral-900 px-2 py-1";

/** Narrow results to a clip, a person, a scene, a minimum technical score, or shots with speech. */
export function SearchFilters({ projectId, value, onChange }: { projectId: string; value: FilterValues; onChange: (v: FilterValues) => void }) {
  const path = { path: { project_id: projectId } };
  const media = useQuery(listMediaOptions(path)).data ?? [];
  const actors = useQuery(listActorsOptions(path)).data?.actors ?? [];
  const scenes = useQuery(listScenesOptions(path)).data?.scenes ?? [];
  const set = (patch: Partial<FilterValues>) => onChange({ ...value, ...patch });
  return (
    <fieldset className="flex flex-wrap items-center gap-3 text-xs text-neutral-300">
      <legend className="sr-only">Filters</legend>
      <label>
        Clip{" "}
        <select className={SELECT} value={value.media_id ?? ""} onChange={(e) => set({ media_id: e.target.value || undefined })}>
          <option value="">Any</option>
          {media.map((m) => (
            <option key={m.id} value={m.id}>
              {m.filename}
            </option>
          ))}
        </select>
      </label>
      <label>
        Person{" "}
        <select className={SELECT} value={value.actor_id ?? ""} onChange={(e) => set({ actor_id: e.target.value || undefined })}>
          <option value="">Anyone</option>
          {actors.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Scene{" "}
        <select className={SELECT} value={value.scene_id ?? ""} onChange={(e) => set({ scene_id: e.target.value || undefined })}>
          <option value="">Any</option>
          {scenes.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Technical score at least{" "}
        <select className={SELECT} value={value.min_quality ?? ""} onChange={(e) => set({ min_quality: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">Any</option>
          {[0.5, 0.7, 0.9].map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={value.has_dialogue} onChange={(e) => set({ has_dialogue: e.target.checked })} /> With speech
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={value.selects_only} onChange={(e) => set({ selects_only: e.target.checked })} /> Selects only
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={value.include_rejected} onChange={(e) => set({ include_rejected: e.target.checked })} /> Show rejected
      </label>
    </fieldset>
  );
}
