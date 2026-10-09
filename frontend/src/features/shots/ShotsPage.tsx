import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import type { ProjectShotOut } from "../../api";
import { listProjectShotsOptions } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { formatTime } from "../library/format";

export function ShotsPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to see its shots.
      </EmptyState>
    );
  }
  return <Shots projectId={projectId} />;
}

function ShotCard({ shot }: { shot: ProjectShotOut }) {
  const key = shot.keyframes[Math.floor(shot.keyframes.length / 2)];
  const label = `${shot.filename}, shot ${shot.index + 1}`;
  return (
    <li className="overflow-hidden rounded border border-neutral-800 bg-neutral-900">
      <Link to={`/library/${shot.media_id}?t=${shot.start_s}`} aria-label={`Open ${label}`} className="block hover:bg-neutral-800/60">
        <div className="flex aspect-video items-center justify-center bg-black text-xs text-neutral-500">
          {key ? (
            <img src={`/api/keyframes/${key.id}/image`} alt="" className="h-full w-full object-cover" loading="lazy" />
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
    </li>
  );
}

function Shots({ projectId }: { projectId: string }) {
  const { data, error, isPending, refetch } = useQuery(listProjectShotsOptions({ path: { project_id: projectId } }));
  const clips = new Set(data?.map((s) => s.media_id)).size;
  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Shots</h1>
        <p className="text-sm text-neutral-400">
          A shot is a continuous run of frames between two cuts, found automatically.
          {!!data?.length && ` ${data.length} shots in ${clips} ${clips === 1 ? "clip" : "clips"}.`} Grouping shots into
          scenes arrives in Phase 8.
        </p>
      </div>
      {isPending && <Loading label="Loading shots…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.length === 0 && (
        <EmptyState title="No shots yet">
          Shots appear here once footage in the <Link className="underline" to="/library">Library</Link> has finished
          processing.
        </EmptyState>
      )}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3">
        {data?.map((s) => <ShotCard key={s.id} shot={s} />)}
      </ul>
    </section>
  );
}
