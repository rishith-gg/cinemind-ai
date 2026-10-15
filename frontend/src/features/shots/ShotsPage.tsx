import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { listScenesOptions, regroupScenesMutation } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { SceneBlock, ShotCard } from "./SceneBlock";
import { useSetScenes } from "./scenes";

export function ShotsPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to see its shots and scenes.
      </EmptyState>
    );
  }
  return <Scenes projectId={projectId} />;
}

function Scenes({ projectId }: { projectId: string }) {
  const { data, error, isPending, refetch } = useQuery(listScenesOptions({ path: { project_id: projectId } }));
  const setScenes = useSetScenes(projectId);
  const regroup = useMutation({
    ...regroupScenesMutation(),
    onSuccess: (fresh) => {
      setScenes(fresh);
      toast.success("Grouped again. Your splits, joins and names were kept.");
    },
  });
  const shots = (data?.scenes.reduce((n, s) => n + s.shot_count, 0) ?? 0) + (data?.ungrouped.length ?? 0);
  const clips = new Set([...(data?.scenes.flatMap((s) => s.shots) ?? []), ...(data?.ungrouped ?? [])].map((s) => s.media_id)).size;
  const cfg = data?.settings;
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-xl font-semibold">Shots and scenes</h1>
          <p className="text-sm text-neutral-400">
            A shot is a continuous run of frames between two cuts. A scene is a run of neighbouring shots (clips in file-name
            order) that look alike: picture vectors and colour, weighted {cfg?.visual_weight ?? 0.7} / {cfg?.color_weight ?? 0.3},
            joined at a similarity of {cfg?.join_similarity ?? 0.8} or more. That limit is a convention, not a measured value, so
            scenes are suggestions: split, join and rename them; your edits stay when the project is grouped again.
            {shots > 0 && ` ${shots} shots in ${clips} ${clips === 1 ? "clip" : "clips"}, ${data?.scenes.length ?? 0} scenes.`}
          </p>
        </div>
        {shots > 0 && (
          <button
            className="rounded border border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-800"
            disabled={regroup.isPending}
            onClick={() => regroup.mutate({ path: { project_id: projectId } })}
          >
            Group again
          </button>
        )}
      </div>
      {isPending && <Loading label="Loading scenes…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.message && (
        <p role="alert" className="rounded border border-amber-800 bg-amber-950 p-3 text-sm">
          {data.message}
        </p>
      )}
      {data && shots === 0 && (
        <EmptyState title="No shots yet">
          Shots appear here once footage in the <Link className="underline" to="/library">Library</Link> has finished
          processing.
        </EmptyState>
      )}
      <div className="flex flex-wrap items-start gap-3">
        {data?.scenes.map((scene, i) => (
          <SceneBlock key={scene.id} projectId={projectId} scene={scene} first={i === 0} />
        ))}
      </div>
      {!!data?.ungrouped.length && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Not grouped yet</h2>
          <p className="text-xs text-neutral-400">
            These shots arrived after the last grouping. Scenes are grouped again when processing is done, or press Group again.
          </p>
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3">
            {data.ungrouped.map((s) => (
              <ShotCard key={s.shot_id} projectId={projectId} shot={s} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
