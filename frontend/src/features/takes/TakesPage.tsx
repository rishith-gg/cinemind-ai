import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import type { TakeGroupsOut } from "../../api";
import { listTakeGroupsOptions, regroupTakesMutation, setTakeApartMutation } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatTime } from "../library/format";
import { TakeGroupCard, useSetTakes } from "./TakeGroupCard";

export function TakesPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to see its takes.
      </EmptyState>
    );
  }
  return <Takes projectId={projectId} />;
}

function Rules({ data }: { data: TakeGroupsOut }) {
  const s = data.settings as Record<string, number>;
  return (
    <p className="text-sm text-neutral-400">
      A take is one attempt at the same line or action. Two shots are grouped as takes when both have speech and their words agree
      at least {s.text_min} (pictures at least {s.picture_min_with_text}), or, without speech, when their pictures agree at least{" "}
      {s.picture_min} and they are at most {s.max_apart} shots apart in file-name order. The best take has the highest mean of its
      signals: focus, exposure and audio, plus for speech how complete and how clean the line is. These limits and weights are
      conventions, so groups and best takes are suggestions: pick another best take or take a shot out of a group; your answers stay
      when takes are looked for again.
      {data.grouped_at &&
        ` ${data.details.groups ?? 0} groups holding ${data.details.shots_in_groups ?? 0} of ${data.shots} shots (${data.details.shots_with_speech ?? 0} with speech).`}
    </p>
  );
}

function Takes({ projectId }: { projectId: string }) {
  const { data, error, isPending, refetch } = useQuery(listTakeGroupsOptions({ path: { project_id: projectId } }));
  const setTakes = useSetTakes(projectId);
  const regroup = useMutation({
    ...regroupTakesMutation(),
    onSuccess: (fresh) => {
      setTakes(fresh);
      toast.success(`Looked for takes: ${fresh.groups.length} ${fresh.groups.length === 1 ? "group" : "groups"}. Your answers were kept.`);
    },
  });
  const undo = useMutation({
    ...setTakeApartMutation(),
    onSuccess: (fresh) => {
      setTakes(fresh);
      toast.success("Grouped by the signals again.");
    },
  });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl space-y-1">
          <h1 className="text-xl font-semibold">Takes</h1>
          {data && <Rules data={data} />}
        </div>
        {!!data?.shots && (
          <button
            className="rounded border border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-800"
            disabled={regroup.isPending}
            onClick={() => regroup.mutate({ path: { project_id: projectId } })}
          >
            {data.grouped_at ? "Look for takes again" : "Find takes"}
          </button>
        )}
      </div>
      {isPending && <Loading label="Loading takes…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.message && (
        <p role="alert" className="rounded border border-amber-800 bg-amber-950 p-3 text-sm">
          {data.message}
        </p>
      )}
      {data && data.shots === 0 && (
        <EmptyState title="No shots yet">
          Takes are looked for once footage in the <Link className="underline" to="/library">Library</Link> has finished processing.
        </EmptyState>
      )}
      {data && data.shots > 0 && data.grouped_at && data.groups.length === 0 && (
        <EmptyState title="No repeated takes found">
          No two shots say the same words or show the same picture close together. If some are takes, look at the limits under{" "}
          <code>[takes]</code> in the settings.
        </EmptyState>
      )}
      <div className="space-y-3">
        {data?.groups.map((g) => (
          <TakeGroupCard key={g.id} projectId={projectId} group={g} />
        ))}
      </div>
      {!!data?.kept_apart.length && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Taken out of a group by you</h2>
          <ul className="space-y-1 text-sm">
            {data.kept_apart.map((s) => (
              <li key={s.shot_id} className="flex items-center gap-3">
                <span>
                  {s.filename} · shot {s.index + 1} ({formatTime(s.start_s)} – {formatTime(s.end_s)})
                </span>
                <button
                  className="text-xs text-blue-300 underline"
                  disabled={undo.isPending}
                  onClick={() => undo.mutate({ path: { project_id: projectId }, body: { shot_id: s.shot_id, apart: false } })}
                >
                  Undo
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
