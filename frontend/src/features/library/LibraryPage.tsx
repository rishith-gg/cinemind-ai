import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { listMediaOptions, listMediaQueryKey, processProjectMutation } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { ImportPanel } from "./ImportPanel";
import { MediaCard } from "./MediaCard";

export function LibraryPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to import footage.
      </EmptyState>
    );
  }
  return <Library projectId={projectId} />;
}

function Library({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [importing, setImporting] = useState(false);
  const { data, error, isPending, refetch } = useQuery(listMediaOptions({ path: { project_id: projectId } }));
  const refresh = () => qc.invalidateQueries({ queryKey: listMediaQueryKey({ path: { project_id: projectId } }) });
  const reprocess = useMutation({
    ...processProjectMutation(),
    onSuccess: () => {
      toast.info("Processing queued. Finished steps are skipped.");
      void refresh();
    },
  });

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Library</h1>
        <div className="flex gap-2">
          {!!data?.length && (
            <button
              className="rounded bg-neutral-800 px-3 py-2 text-sm"
              disabled={reprocess.isPending}
              onClick={() => reprocess.mutate({ path: { project_id: projectId } })}
            >
              Process all
            </button>
          )}
          <button className="rounded bg-blue-600 px-4 py-2 text-sm font-medium" onClick={() => setImporting((v) => !v)}>
            {importing ? "Close import" : "Import footage"}
          </button>
        </div>
      </div>
      {importing && <ImportPanel projectId={projectId} onImported={() => void refresh()} />}
      {isPending && <Loading label="Loading library…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.length === 0 && !importing && (
        <EmptyState title="No footage yet">
          Choose “Import footage” to add a folder from an approved media location, or upload a file. Your originals are
          never moved or changed.
        </EmptyState>
      )}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
        {data?.map((m) => <MediaCard key={m.id} media={m} />)}
      </ul>
    </section>
  );
}
