import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import type { RoughCutCreate } from "../../api";
import {
  createRoughCutMutation,
  listActorsOptions,
  listScenesOptions,
  listTimelinesOptions,
  listTimelinesQueryKey,
} from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration } from "../library/format";

const ORDERS: Record<string, string> = {
  "": "From the brief (else source order)",
  chronological: "Source order (file name, then time)",
  scene: "By scene",
  score: "Best first",
};

export function TimelinePage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to build a rough cut.
      </EmptyState>
    );
  }
  return <RoughCuts projectId={projectId} />;
}

function BriefForm({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const path = { project_id: projectId };
  const [brief, setBrief] = useState("");
  const [minutes, setMinutes] = useState("");
  const [order, setOrder] = useState("");
  const [actor, setActor] = useState("");
  const [scene, setScene] = useState("");
  const actors = useQuery(listActorsOptions({ path }));
  const scenes = useQuery(listScenesOptions({ path }));
  const build = useMutation({
    ...createRoughCutMutation(),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: listTimelinesQueryKey({ path }) });
      toast.success(`Rough cut built: ${t.item_count} clips, ${formatDuration(t.duration_s)}.`);
      void navigate(`/timeline/${t.id}`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const named = (actors.data?.actors ?? []).filter((a) => a.named);

  return (
    <form
      className="space-y-3 rounded border border-neutral-800 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        const seconds = Number(minutes) * 60;
        const body: RoughCutCreate = {
          brief: brief.trim(),
          target_s: minutes && seconds >= 1 ? seconds : undefined,
          order: (order || undefined) as RoughCutCreate["order"],
          actor_id: actor || undefined,
          scene_id: scene || undefined,
        };
        build.mutate({ path, body });
      }}
    >
      <label className="block text-sm">
        <span className="mb-1 block text-neutral-400">Brief</span>
        <textarea
          className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5"
          rows={2}
          maxLength={1000}
          required
          placeholder="2-minute sequence about the grandfather walking home at night"
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label>
          <span className="mb-1 block text-neutral-400">Length in minutes (optional)</span>
          <input
            className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5"
            type="number"
            min={0.05}
            max={60}
            step="any"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </label>
        <label>
          <span className="mb-1 block text-neutral-400">Order</span>
          <select className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5" aria-label="Order" value={order} onChange={(e) => setOrder(e.target.value)}>
            {Object.entries(ORDERS).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-neutral-400">Only shots with</span>
          <select className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5" aria-label="Only shots with" value={actor} onChange={(e) => setActor(e.target.value)}>
            <option value="">Anyone</option>
            {named.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-neutral-400">Only scene</span>
          <select className="max-w-48 rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5" aria-label="Only scene" value={scene} onChange={(e) => setScene(e.target.value)}>
            <option value="">Any</option>
            {(scenes.data?.scenes ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <button className="rounded bg-blue-600 px-4 py-2 font-medium disabled:opacity-50" disabled={build.isPending || !brief.trim()}>
          {build.isPending ? "Building…" : "Build rough cut"}
        </button>
      </div>
      {build.isPending && (
        <p role="status" className="text-sm text-neutral-400">
          Searching the footage and choosing clips. The first search after starting the app loads the models and can take
          half a minute.
        </p>
      )}
      <p className="text-xs text-neutral-500">
        Rules read the brief (length, order, what to look for); no language model is used. Shots you rejected, and shots
        below the quality limit, are left out. The result is a starting point for you to edit, not a finished cut.
      </p>
    </form>
  );
}

function RoughCuts({ projectId }: { projectId: string }) {
  const { data, error, isPending, refetch } = useQuery(listTimelinesOptions({ path: { project_id: projectId } }));
  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Timeline</h1>
        <p className="text-sm text-neutral-400">
          Describe the sequence you want. CineMind searches your footage, picks and trims clips, and builds an AI-assisted
          rough cut that you then reorder, trim, swap and export to your editor.
        </p>
      </div>
      <BriefForm projectId={projectId} />
      <div className="space-y-3">
        <h2 className="font-medium">Timelines</h2>
        {isPending && <Loading label="Loading timelines…" />}
        {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
        {data?.length === 0 && <EmptyState title="No timelines yet">Write a brief above to build the first rough cut.</EmptyState>}
        <ul className="space-y-2">
          {data?.map((t) => (
            <li key={t.id}>
              <Link
                to={`/timeline/${t.id}`}
                className="block rounded border border-neutral-800 bg-neutral-900 p-3 hover:border-neutral-600"
              >
                <span className="font-medium">{t.name}</span>{" "}
                <span className="text-sm text-neutral-400">
                  · {t.kind === "rough_cut" ? "AI-assisted rough cut" : t.kind === "script_cut" ? "script assembly" : "every shot"} · {t.item_count} clips · {formatDuration(t.duration_s)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
