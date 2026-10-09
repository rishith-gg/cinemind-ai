import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { exportTimeline, type TimelineOut } from "../../api";
import {
  createTimelineMutation,
  deleteTimelineMutation,
  listTimelinesOptions,
  listTimelinesQueryKey,
} from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration, rateLabel } from "../library/format";

const RATES: [number, number][] = [
  [24000, 1001],
  [24, 1],
  [25, 1],
  [30000, 1001],
  [30, 1],
  [50, 1],
  [60000, 1001],
  [60, 1],
];
const FORMATS: Record<string, string> = {
  fcp7xml: "FCP7 XML (DaVinci Resolve)",
  edl: "EDL",
  otio: "OTIO",
};

export function ExportPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to export a timeline.
      </EmptyState>
    );
  }
  return <Export projectId={projectId} />;
}

/** Fetch the export and hand it to the browser as a file, so a failure (timeline deleted
 * elsewhere, format not possible, disk full) is shown instead of a broken download. */
async function download(timelineId: string, fmt: string) {
  try {
    const { data, error, response } = await exportTimeline({ path: { timeline_id: timelineId, fmt }, parseAs: "blob" });
    if (error || !(data instanceof Blob) || !response?.ok) {
      toast.error(errorMessage(error));
      return;
    }
    const header = response.headers.get("content-disposition") ?? "";
    const encoded = /filename\*=utf-8''([^;]+)/i.exec(header)?.[1];
    const name = encoded ? decodeURIComponent(encoded) : (/filename="([^"]+)"/i.exec(header)?.[1] ?? `timeline.${fmt}`);
    const url = URL.createObjectURL(data);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast.error(errorMessage(e));
  }
}

function TimelineCard({ timeline, onDelete }: { timeline: TimelineOut; onDelete: () => void }) {
  const excluded = (timeline.params.excluded as string[] | undefined) ?? [];
  return (
    <li className="space-y-3 rounded border border-neutral-800 bg-neutral-900 p-4" aria-label={timeline.name}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">{timeline.name}</h3>
          <p className="text-sm text-neutral-400">
            {timeline.item_count} cuts · {formatDuration(timeline.duration_s)} · {rateLabel(timeline.fps_num, timeline.fps_den)}{" "}
            fps · {timeline.width}×{timeline.height} · every shot, in file-name order
          </p>
        </div>
        <button className="rounded bg-neutral-800 px-3 py-1.5 text-sm hover:text-red-400" onClick={onDelete}>
          Delete
        </button>
      </div>
      {timeline.warnings.map((w) => (
        <p key={w} role="note" className="rounded border border-amber-800 bg-amber-950 p-2 text-sm">
          {w}
        </p>
      ))}
      {excluded.length > 0 && (
        <p className="text-sm text-neutral-400">
          Left out (other frame rate): {excluded.join(", ")}
        </p>
      )}
      {timeline.item_count === 0 ? (
        <p className="text-sm text-neutral-400">Its clips were removed from the project, so there is nothing to export.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {timeline.formats.map((f) => (
            <button
              key={f}
              type="button"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium"
              onClick={() => void download(timeline.id, f)}
            >
              Download {FORMATS[f] ?? f}
            </button>
          ))}
        </div>
      )}
      <p className="text-xs text-neutral-500">
        Each download is also saved in <code>{timeline.export_dir}</code>. The files point at your original footage, not
        the proxies.
      </p>
    </li>
  );
}

function Export({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [name, setName] = useState("All shots");
  const [rate, setRate] = useState("auto");
  const [exclude, setExclude] = useState(false);
  const path = { project_id: projectId };
  const { data, error, isPending, refetch } = useQuery(listTimelinesOptions({ path }));
  const refresh = () => qc.invalidateQueries({ queryKey: listTimelinesQueryKey({ path }) });
  const build = useMutation({
    ...createTimelineMutation(),
    onSuccess: (t) => {
      toast.success(`Timeline “${t.name}” built with ${t.item_count} cuts.`);
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    ...deleteTimelineMutation(),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Export</h1>
        <p className="text-sm text-neutral-400">
          Build a timeline and open it in your editor. For now there is one kind: every detected shot, in order, with
          nothing chosen or ranked. It exists to check that timelines arrive correctly in DaVinci Resolve. The
          AI-assisted rough cut is built in a later phase.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-4 rounded border border-neutral-800 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          const fps = rate === "auto" ? undefined : (rate.split("/").map(Number) as [number, number]);
          build.mutate({ path, body: { name: name.trim() || "All shots", fps, mixed_rates: exclude ? "exclude" : "include" } });
        }}
      >
        <label className="text-sm">
          <span className="mb-1 block text-neutral-400">Timeline name</span>
          <input
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5"
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-neutral-400">Frame rate</span>
          <select
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          >
            <option value="auto">Auto (the rate most clips have)</option>
            {RATES.map(([n, d]) => (
              <option key={`${n}/${d}`} value={`${n}/${d}`}>
                {rateLabel(n, d)} fps
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
          Leave out clips at other frame rates
        </label>
        <button className="rounded bg-blue-600 px-4 py-2 text-sm font-medium disabled:opacity-50" disabled={build.isPending}>
          {build.isPending ? "Building…" : "Build timeline"}
        </button>
      </form>

      <div className="space-y-3">
        <h2 className="font-medium">Timelines</h2>
        {isPending && <Loading label="Loading timelines…" />}
        {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
        {data?.length === 0 && (
          <EmptyState title="No timelines yet">Build one above once your footage has finished processing.</EmptyState>
        )}
        <ul className="space-y-3">
          {data?.map((t) => (
            <TimelineCard
              key={t.id}
              timeline={t}
              onDelete={() => {
                if (window.confirm(`Delete the timeline “${t.name}”? Exported files stay on disk.`))
                  remove.mutate({ path: { timeline_id: t.id } });
              }}
            />
          ))}
        </ul>
      </div>

      <details className="rounded border border-neutral-800 p-4 text-sm">
        <summary className="cursor-pointer font-medium">Opening the file in DaVinci Resolve</summary>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-neutral-300">
          <li>Create a new Resolve project and set its timeline frame rate to the timeline’s rate before adding media.</li>
          <li>Drag your footage folder into the Media Pool.</li>
          <li>Use File → Import → Timeline… and pick the downloaded .xml file.</li>
          <li>Check that every cut is present, in order, with sound, and that the clips are online (not red).</li>
        </ol>
        <p className="mt-3 text-neutral-400">The full checklist is in docs/TESTING.md.</p>
      </details>
    </section>
  );
}
