import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { listProjectTranscriptsOptions, searchTranscriptsOptions } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { formatDuration, formatTime } from "../library/format";
import { languageName, STATUS_LABEL, UNCERTAIN_HINT } from "./labels";
import { SpokenLanguages } from "./SpokenLanguages";

export function TranscriptsPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to see its transcripts.
      </EmptyState>
    );
  }
  return <Transcripts projectId={projectId} />;
}

function Results({ projectId, query, unsure }: { projectId: string; query: string; unsure: boolean }) {
  const { data, error, isPending } = useQuery(
    searchTranscriptsOptions({ path: { project_id: projectId }, query: { q: query, include_uncertain: unsure } }),
  );
  if (isPending) return <Loading label="Searching…" />;
  if (error) return <ErrorState message={errorMessage(error)} />;
  if (data.hits.length === 0) {
    return (
      <p role="status" className="text-sm text-neutral-400">
        No transcript contains {data.terms.length > 1 ? "all of " : ""}“{data.terms.join(" ")}”. Words are matched from their
        beginning, in the language they were transcribed in.{!unsure && " Lines the speech model was unsure about are left out."}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p role="status" className="text-xs text-neutral-400">
        {data.hits.length} {data.hits.length === 1 ? "match" : "matches"}, best first (BM25). Click one to open the clip at that
        moment.
      </p>
      <ol aria-label="Search results" className="space-y-1">
        {data.hits.map((hit) => (
          <li key={hit.segment_id}>
            <Link
              to={`/library/${hit.media_id}?t=${hit.jump_s}`}
              className="block rounded border border-neutral-800 bg-neutral-900 p-2 text-sm hover:bg-neutral-800/60"
            >
              <span className="font-mono text-xs text-blue-300">{formatTime(hit.jump_s)}</span>{" "}
              <span className="text-xs text-neutral-400">{hit.filename}</span>
              {hit.uncertain && (
                <span title={UNCERTAIN_HINT} className="ml-2 rounded bg-amber-900/50 px-1 text-xs text-amber-300">
                  uncertain
                </span>
              )}
              <span className="block">
                {hit.parts.map((part, i) =>
                  part.match ? (
                    <mark key={i} className="rounded bg-yellow-500/80 px-0.5 text-black">
                      {part.text}
                    </mark>
                  ) : (
                    <span key={i}>{part.text}</span>
                  ),
                )}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Transcripts({ projectId }: { projectId: string }) {
  const [params, setParams] = useSearchParams();
  const query = params.get("q")?.trim() ?? "";
  const unsure = params.get("unsure") === "1";
  const [draft, setDraft] = useState(query);
  const { data, error, isPending, refetch } = useQuery(listProjectTranscriptsOptions({ path: { project_id: projectId } }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(draft.trim() ? { q: draft.trim(), ...(unsure ? { unsure: "1" } : {}) } : {});
  };
  const setUnsure = (on: boolean) => setParams({ ...(query ? { q: query } : {}), ...(on ? { unsure: "1" } : {}) });
  const missing = data?.find((c) => c.status === "model_missing");
  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Transcripts</h1>
        <p className="text-sm text-neutral-400">
          Speech in your clips, turned into text on this machine by a Whisper model. Search for a word to jump to the moment it
          is spoken.
        </p>
      </div>
      <form role="search" className="flex gap-2" onSubmit={submit}>
        <input
          type="search"
          aria-label="Search transcripts"
          placeholder="Search for spoken words"
          maxLength={200}
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="rounded bg-blue-600 px-3 py-1.5 text-sm">Search</button>
      </form>
      <label className="flex items-center gap-1 text-xs text-neutral-400">
        <input type="checkbox" checked={unsure} onChange={(e) => setUnsure(e.target.checked)} /> Include lines the speech model was
        unsure about
      </label>
      {query && <Results projectId={projectId} query={query} unsure={unsure} />}
      {missing && (
        <p role="alert" className="rounded border border-amber-800 bg-amber-950 p-3 text-sm">
          {missing.message}
        </p>
      )}
      <SpokenLanguages projectId={projectId} />
      {isPending && <Loading label="Loading transcripts…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.length === 0 && (
        <EmptyState title="No clips yet">
          <Link className="underline" to="/library">
            Import footage
          </Link>{" "}
          to transcribe it.
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Transcript status per clip</caption>
          <thead className="text-xs text-neutral-400">
            <tr>
              {["Clip", "Transcript", "Language", "Speech", "Words"].map((h) => (
                <th key={h} scope="col" className="py-1 font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((clip) => (
              <tr key={clip.media_id} className="border-t border-neutral-800">
                <td className="py-1">
                  <Link className="underline" to={`/library/${clip.media_id}`}>
                    {clip.filename}
                  </Link>
                </td>
                <td className={clip.status === "done" ? "" : "text-neutral-400"} title={clip.message ?? undefined}>
                  {STATUS_LABEL[clip.status]}
                </td>
                <td>{clip.language ? languageName(clip.language) : "–"}</td>
                <td className="font-mono text-xs">
                  {clip.status === "done" || clip.status === "not_written" ? `${formatDuration(clip.speech_s)} of ${formatDuration(clip.duration_s)}` : "–"}
                </td>
                <td>{clip.words || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
