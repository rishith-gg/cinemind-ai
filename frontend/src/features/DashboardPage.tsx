import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { ProjectStatsOut } from "../api";
import { getProjectOptions, getProjectStatsOptions, listProjectsOptions } from "../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../components/states";
import { useCurrentProject } from "../lib/currentProject";
import { errorMessage } from "../lib/errors";
import { formatBytes, formatDuration } from "./library/format";

const BAND_LABELS = ["0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1"];
const STATE_LABELS: Record<string, string> = {
  succeeded: "processed",
  running: "processing",
  queued: "waiting",
  failed: "failed",
  cancelled: "cancelled",
  "not processed": "not processed",
};
const TRANSCRIPT_LABELS: Record<string, string> = {
  done: "transcribed",
  no_speech: "no speech",
  no_audio: "no audio",
  not_written: "detect-only language",
  model_missing: "model missing",
  audio_unreadable: "audio unreadable",
};

export function DashboardPage() {
  const projectId = useCurrentProject((s) => s.id);
  const projects = useQuery(listProjectsOptions());
  return (
    <section className="space-y-5">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      {projects.isPending && <Loading />}
      {projects.error && <ErrorState message={errorMessage(projects.error)} onRetry={() => void projects.refetch()} />}
      {projects.data && !projectId && (
        <EmptyState title={projects.data.length ? "No project selected" : "No projects yet"}>
          <Link className="underline" to="/projects">
            {projects.data.length ? "Choose a project" : "Create a project"}
          </Link>{" "}
          to see its footage statistics.
        </EmptyState>
      )}
      {projectId && <ProjectDashboard projectId={projectId} />}
    </section>
  );
}

function ProjectDashboard({ projectId }: { projectId: string }) {
  const project = useQuery(getProjectOptions({ path: { project_id: projectId } }));
  const { data, error, isPending, refetch } = useQuery(getProjectStatsOptions({ path: { project_id: projectId } }));
  if (isPending) return <Loading label="Loading footage statistics…" />;
  if (error) return <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />;
  if (data.clips === 0) {
    return (
      <EmptyState title={`${project.data?.name ?? "This project"} has no footage yet`}>
        <Link className="underline" to="/library">
          Import clips in the Library
        </Link>{" "}
        and their statistics appear here.
      </EmptyState>
    );
  }
  return (
    <div className="space-y-5">
      <p className="text-sm text-neutral-400">
        {project.data?.name} · counts read from the project database; scores are suggestions to review, not verdicts.
      </p>
      <Tiles data={data} />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Processing data={data} />
        <QualityBands data={data} />
        <Formats data={data} />
        <Speech data={data} />
      </div>
      <NextSteps data={data} />
    </div>
  );
}

function Tile({ label, value, note, to }: { label: string; value: string; note?: string; to?: string }) {
  const body = (
    <>
      <p className="text-xs uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-0.5 text-xs text-neutral-400">{note}</p>}
    </>
  );
  const cls = "block rounded border border-neutral-800 bg-neutral-900 p-3";
  return to ? (
    <Link to={to} className={`${cls} hover:border-neutral-600`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function Tiles({ data }: { data: ProjectStatsOut }) {
  const timelines = Object.values(data.timelines).reduce((a, b) => a + b, 0);
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Tile label="Clips" value={String(data.clips)} note={`${formatDuration(data.duration_s)} · ${formatBytes(data.size_bytes)}`} to="/library" />
      <Tile label="Shots" value={String(data.shots)} note={`${data.scenes} scenes`} to="/shots" />
      <Tile label="Actors" value={String(data.actors)} note={`${data.actors_named} named by you`} to="/actors" />
      <Tile label="Speech" value={formatDuration(data.speech_s)} note={`${data.segments} transcript lines`} to="/transcripts" />
      <Tile
        label="Low-quality shots"
        value={String(data.low_quality)}
        note={`score below ${data.low_quality_below} of ${data.quality_measured} measured`}
        to="/library"
      />
      <Tile label="Take groups" value={String(data.take_groups)} note={`${data.shots_in_takes} shots in groups`} to="/takes" />
      <Tile label="Your marks" value={`${data.selected} / ${data.rejected}`} note="selected / rejected shots" to="/shots" />
      <Tile label="Timelines" value={String(timelines)} note={timelines ? Object.entries(data.timelines).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ") : "build one on the Timeline page"} to="/timeline" />
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2 rounded border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Rows({ rows, empty }: { rows: [string, string][]; empty: string }) {
  if (!rows.length) return <p className="text-sm text-neutral-400">{empty}</p>;
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-neutral-400">{k}</dt>
          <dd className="text-right tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Processing({ data }: { data: ProjectStatsOut }) {
  const rows = Object.entries(data.states).map(([k, v]): [string, string] => [STATE_LABELS[k] ?? k, `${v} ${v === 1 ? "clip" : "clips"}`]);
  return (
    <Panel title="Processing">
      <Rows rows={rows} empty="No clip has been processed yet." />
      {!!data.states.failed && (
        <p className="text-xs text-amber-300">
          Open the failed clips in the <Link className="underline" to="/library">Library</Link> to see what went wrong and retry.
        </p>
      )}
    </Panel>
  );
}

/** One series (shots per score band), one hue, counts labelled on each bar; the title gives exact values on hover. */
function QualityBands({ data }: { data: ProjectStatsOut }) {
  const most = Math.max(1, ...data.quality_bands);
  const flags = Object.entries(data.qc_flags).map(([k, v]): [string, string] => [k.replaceAll("_", " "), String(v)]);
  return (
    <Panel title="Technical quality of shots">
      {data.quality_measured === 0 ? (
        <p className="text-sm text-neutral-400">Quality has not been measured yet.</p>
      ) : (
        <figure>
          <div role="img" aria-label={`Shots per quality score band: ${data.quality_bands.map((n, i) => `${BAND_LABELS[i]}: ${n}`).join(", ")}`} className="flex h-28 items-end gap-0.5 border-b border-neutral-700">
            {data.quality_bands.map((n, i) => (
              <div key={BAND_LABELS[i]} className="flex h-full flex-1 flex-col justify-end" title={`${n} shots scored ${BAND_LABELS[i]}`}>
                <span className="mb-0.5 text-center text-xs tabular-nums text-neutral-300">{n}</span>
                <div className="rounded-t bg-blue-500" style={{ height: `${(n / most) * 80}%`, minHeight: n ? 2 : 0 }} />
              </div>
            ))}
          </div>
          <div className="mt-1 flex gap-0.5 text-center text-[11px] text-neutral-400">
            {BAND_LABELS.map((b) => (
              <span key={b} className="flex-1">
                {b}
              </span>
            ))}
          </div>
          <figcaption className="mt-1 text-xs text-neutral-400">Shots per Technical Quality Score (focus, exposure, contrast).</figcaption>
        </figure>
      )}
      <h3 className="pt-1 text-xs font-semibold text-neutral-300">Quality flags</h3>
      <Rows rows={flags} empty="No quality problems flagged." />
    </Panel>
  );
}

function Formats({ data }: { data: ProjectStatsOut }) {
  const rows: [string, string][] = [
    ...Object.entries(data.codecs).map(([k, v]): [string, string] => [`${k.toUpperCase()} video`, `${v} clips`]),
    ["Portrait / landscape", `${data.portrait} / ${data.landscape}`],
    ["Frame rates (fps)", data.frame_rates.join(", ") || "—"],
    ["Variable frame rate", `${data.variable_rate} clips`],
    ["Without audio", `${data.no_audio} clips`],
  ];
  return (
    <Panel title="Footage formats">
      <Rows rows={rows} empty="" />
      {data.frame_rates.length > 1 && (
        <p className="text-xs text-neutral-400">Mixed frame rates are converted to the timeline rate on export (exact rational rates).</p>
      )}
    </Panel>
  );
}

function Speech({ data }: { data: ProjectStatsOut }) {
  const rows: [string, string][] = [
    ...Object.entries(data.transcripts).map(([k, v]): [string, string] => [TRANSCRIPT_LABELS[k] ?? k, `${v} clips`]),
    ...Object.entries(data.languages).map(([k, v]): [string, string] => [`language: ${k}`, `${v} clips`]),
  ];
  return (
    <Panel title="Speech">
      <Rows rows={rows} empty="No transcripts yet." />
    </Panel>
  );
}

function NextSteps({ data }: { data: ProjectStatsOut }) {
  const steps: [string, string][] = [];
  if (data.states["not processed"]) steps.push(["/library", "Process the clips that have not been processed"]);
  if (data.actors > data.actors_named) steps.push(["/actors", "Name the actors"]);
  if (data.selected + data.rejected === 0) steps.push(["/search", "Search and select or reject shots: marks steer the rough cut"]);
  if (data.take_groups) steps.push(["/takes", "Check the suggested best takes"]);
  steps.push(["/timeline", "Build an AI-assisted rough cut from a one-sentence brief"]);
  return (
    <Panel title="Next steps">
      <ul className="list-inside list-disc space-y-1 text-sm">
        {steps.map(([to, text]) => (
          <li key={text}>
            <Link className="text-blue-300 underline" to={to}>
              {text}
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
