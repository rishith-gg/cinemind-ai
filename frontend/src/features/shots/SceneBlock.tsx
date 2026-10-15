import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { Link } from "react-router";

import type { MarkOut, SceneOut, ScenesOut, SceneShotOut } from "../../api";
import { listScenesQueryKey, renameSceneMutation, setSceneBoundaryMutation } from "../../api/@tanstack/react-query.gen";
import { toast } from "../../lib/toast";
import { formatTime } from "../library/format";
import { MarkButtons } from "../marks/MarkButtons";
import { useSetScenes } from "./scenes";

/** Plain words for how a shot compares with the one before it (the "why" behind the grouping). */
export function similarityNote(shot: SceneShotOut): string {
  const parts = [shot.decision];
  if (shot.visual !== null && shot.visual !== undefined) parts.push(`picture ${shot.visual.toFixed(2)}`);
  if (shot.color !== null && shot.color !== undefined) parts.push(`colour ${shot.color.toFixed(2)}`);
  return parts.join(" · ");
}

/** The scene list with one shot's new mark patched in (no refetch, so the buttons never show
 * the old state in between). */
function withMark(old: ScenesOut | undefined, out: MarkOut): ScenesOut | undefined {
  if (!old) return old;
  const fix = (s: SceneShotOut) => (s.shot_id === out.shot_id ? { ...s, mark: out.mark, stars: out.stars } : s);
  return { ...old, scenes: old.scenes.map((c) => ({ ...c, shots: c.shots.map(fix) })), ungrouped: old.ungrouped.map(fix) };
}

export function ShotCard({ projectId, shot, children }: { projectId: string; shot: SceneShotOut; children?: ReactNode }) {
  const qc = useQueryClient();
  const label = `${shot.filename}, shot ${shot.index + 1}`;
  return (
    <li className="w-44 overflow-hidden rounded border border-neutral-800 bg-neutral-900">
      <Link to={`/library/${shot.media_id}?t=${shot.start_s}`} aria-label={`Open ${label}`} className="block hover:bg-neutral-800/60">
        <div className="flex aspect-video items-center justify-center bg-black text-xs text-neutral-500">
          {shot.keyframe_id ? (
            <img src={`/api/keyframes/${shot.keyframe_id}/image`} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <span>No keyframe</span>
          )}
        </div>
        <div className="p-2">
          <p className="truncate text-xs font-medium" title={shot.filename}>
            {shot.filename} · {shot.index + 1}
          </p>
          <p className="font-mono text-xs text-neutral-400">
            {formatTime(shot.start_s)} – {formatTime(shot.end_s)}
          </p>
        </div>
      </Link>
      <div className="border-t border-neutral-800 px-2 py-1">
        <MarkButtons
          shotId={shot.shot_id}
          label={label}
          mark={shot.mark ?? null}
          stars={shot.stars ?? 0}
          onChanged={(out) => qc.setQueriesData<ScenesOut>({ queryKey: listScenesQueryKey({ path: { project_id: projectId } }) }, (old) => withMark(old, out))}
        />
      </div>
      {children && <div className="space-y-1 border-t border-neutral-800 p-2 text-xs">{children}</div>}
    </li>
  );
}

function SceneName({ projectId, scene }: { projectId: string; scene: SceneOut }) {
  const setScenes = useSetScenes(projectId);
  const [name, setName] = useState(scene.name);
  const rename = useMutation({
    ...renameSceneMutation(),
    onSuccess: (fresh) => {
      setScenes(fresh);
      toast.success(name.trim() ? `Named ${name.trim()}.` : "Name removed.");
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    rename.mutate({ path: { scene_id: scene.id }, body: { name } });
  };
  return (
    <form className="flex items-center gap-2" onSubmit={submit}>
      <input
        aria-label={`Name of ${scene.name}`}
        maxLength={100}
        className="w-36 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm font-semibold"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button className="rounded bg-blue-600 px-2 py-1 text-xs disabled:opacity-50" disabled={rename.isPending || name === scene.name}>
        Save name
      </button>
    </form>
  );
}

export function SceneBlock({ projectId, scene, first }: { projectId: string; scene: SceneOut; first: boolean }) {
  const setScenes = useSetScenes(projectId);
  const boundary = useMutation({
    ...setSceneBoundaryMutation(),
    onSuccess: (fresh, vars) => {
      setScenes(fresh);
      const done = { split: "New scene started.", join: "Joined with the scene before.", auto: "Back to the automatic decision." };
      toast.success(done[vars.body.decision]);
    },
  });
  const send = (shot_id: string, decision: "split" | "join" | "auto") =>
    boundary.mutate({ path: { project_id: projectId }, body: { shot_id, decision } });
  const opener = scene.shots[0];
  return (
    <article aria-label={scene.name} className="min-w-[12.5rem] max-w-full space-y-2 rounded border border-neutral-800 p-3">
      <header className="flex max-w-[24rem] flex-wrap items-center gap-x-3 gap-y-1">
        <SceneName key={scene.name} projectId={projectId} scene={scene} />
        <span className="text-xs text-neutral-400">
          {scene.shot_count} {scene.shot_count === 1 ? "shot" : "shots"} · {formatTime(scene.duration_s)}
        </span>
        {opener && <span className="text-xs text-neutral-500">Starts here: {opener.decision}</span>}
        {!first && opener && (
          <button className="text-xs text-blue-300 underline" disabled={boundary.isPending} onClick={() => send(opener.shot_id, "join")}>
            Join with the scene before
          </button>
        )}
        {opener?.edit && (
          <button className="text-xs text-blue-300 underline" disabled={boundary.isPending} onClick={() => send(opener.shot_id, "auto")}>
            Undo your edit
          </button>
        )}
      </header>
      <ul className="flex flex-wrap gap-3">
        {scene.shots.map((shot, i) => (
          <ShotCard key={shot.shot_id} projectId={projectId} shot={shot}>
            {i > 0 && (
              <>
                <p className="text-neutral-400" title="How this shot compares with the one before it">
                  {similarityNote(shot)}
                </p>
                <button
                  className="text-blue-300 underline"
                  disabled={boundary.isPending}
                  onClick={() => send(shot.shot_id, "split")}
                  aria-label={`Start a new scene at ${shot.filename}, shot ${shot.index + 1}`}
                >
                  Start a new scene here
                </button>
                {shot.edit && (
                  <button className="ml-3 text-blue-300 underline" disabled={boundary.isPending} onClick={() => send(shot.shot_id, "auto")}>
                    Undo your edit
                  </button>
                )}
              </>
            )}
          </ShotCard>
        ))}
      </ul>
    </article>
  );
}
