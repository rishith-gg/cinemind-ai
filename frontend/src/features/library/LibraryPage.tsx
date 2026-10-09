import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { MediaOut } from "../../api";
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

const FILTERS = {
  all: { label: "All clips", keep: () => true },
  flagged: { label: "With QC flags", keep: (m: MediaOut) => m.qc_flags.length > 0 },
  low: { label: "Low technical score", keep: (m: MediaOut) => m.low_quality },
  clean: { label: "Scored, no QC flags", keep: (m: MediaOut) => m.quality_score != null && !m.low_quality && m.qc_flags.length === 0 },
} as const;
const SORTS = {
  newest: { label: "Newest first", compare: () => 0 },
  worst: { label: "Technical score: lowest first", compare: (a: MediaOut, b: MediaOut) => (a.quality_score ?? 2) - (b.quality_score ?? 2) },
  best: { label: "Technical score: highest first", compare: (a: MediaOut, b: MediaOut) => (b.quality_score ?? -1) - (a.quality_score ?? -1) },
  name: { label: "Name", compare: (a: MediaOut, b: MediaOut) => a.filename.localeCompare(b.filename, undefined, { numeric: true }) },
} as const;

function Library({ projectId }: { projectId: string }) {
  const [filter, setFilter] = useState<keyof typeof FILTERS>("all");
  const [sort, setSort] = useState<keyof typeof SORTS>("newest");
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

  const shown = (data ?? []).filter(FILTERS[filter].keep).sort(SORTS[sort].compare);

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
      {!!data?.length && (
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label>
            <span className="mr-2 text-neutral-400">Show</span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1"
              value={filter}
              onChange={(e) => setFilter(e.target.value as keyof typeof FILTERS)}
            >
              {Object.entries(FILTERS).map(([key, f]) => (
                <option key={key} value={key}>
                  {f.label} ({data.filter(f.keep).length})
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="mr-2 text-neutral-400">Sort</span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1"
              value={sort}
              onChange={(e) => setSort(e.target.value as keyof typeof SORTS)}
            >
              {Object.entries(SORTS).map(([key, s]) => (
                <option key={key} value={key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {!!data?.length && shown.length === 0 && <EmptyState title="No clips match this filter" />}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
        {shown.map((m) => (
          <MediaCard key={m.id} media={m} />
        ))}
      </ul>
    </section>
  );
}
