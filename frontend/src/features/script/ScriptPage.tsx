import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import type { AlignmentOut, ScriptOut } from "../../api";
import {
  alignScriptMutation,
  chooseTakeMutation,
  createScriptAssemblyMutation,
  deleteScriptMutation,
  getScriptOptions,
  getScriptQueryKey,
  listTimelinesQueryKey,
  uploadScriptMutation,
} from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { ScriptLineRow } from "./ScriptLineRow";

export function ScriptPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to add its script.
      </EmptyState>
    );
  }
  return <Script projectId={projectId} />;
}

/** How the match score was made, from what the last alignment recorded. */
export function scoredBy(a: AlignmentOut): string {
  if (!a.semantic) return "scored by words only (the text model is not used)";
  const model = a.text_model ?? "text model";
  return (a.lexical_weight ?? 0) > 0 ? `scored by words and meaning (${model})` : `scored by meaning (${model}); the words set each take's in and out`;
}

function UploadForm({ projectId, onCancel }: { projectId: string; onCancel?: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("Script");
  const [text, setText] = useState("");
  const upload = useMutation({
    ...uploadScriptMutation(),
    onSuccess: (doc) => {
      qc.setQueryData(getScriptQueryKey({ path: { project_id: projectId } }), doc);
      toast.success(`Script read: ${doc.with_take} of ${doc.dialogue_lines} lines found in the footage.`);
      onCancel?.();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form
      className="space-y-3 rounded border border-neutral-800 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        upload.mutate({ path: { project_id: projectId }, body: { name: name.trim() || "Script", text } });
      }}
    >
      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label>
          <span className="mb-1 block text-neutral-400">Name</span>
          <input className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          <span className="mb-1 block text-neutral-400">Open a file (.fountain or .txt)</span>
          <input
            type="file"
            accept=".fountain,.txt,.spmd,text/plain"
            className="text-sm"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setName(file.name.replace(/\.[^.]+$/, ""));
              void file.text().then(setText);
            }}
          />
        </label>
      </div>
      <label className="block text-sm">
        <span className="mb-1 block text-neutral-400">Screenplay</span>
        <textarea
          className="h-48 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 font-mono text-xs"
          required
          placeholder={"INT. KITCHEN - NIGHT\n\nANNA\nYou're late again.\n\nor one line per row, as NAME: words"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className="flex gap-2">
        <button className="rounded bg-blue-600 px-4 py-2 text-sm font-medium disabled:opacity-50" disabled={upload.isPending || !text.trim()}>
          {upload.isPending ? "Finding the lines…" : "Find the lines in the footage"}
        </button>
        {onCancel && (
          <button type="button" className="rounded bg-neutral-800 px-3 py-2 text-sm" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      <p className="text-xs text-neutral-500">
        Each dialogue line is compared with the transcripts (lines marked uncertain are never used). Clips in a language
        without text (detect only) cannot be matched.
      </p>
    </form>
  );
}

function Lines({ doc, projectId }: { doc: ScriptOut; projectId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const key = getScriptQueryKey({ path: { project_id: projectId } });
  const [replacing, setReplacing] = useState(false);
  const settle = (d: ScriptOut) => qc.setQueryData(key, d);
  const fail = (e: unknown) => toast.error(errorMessage(e));
  const scope = { id: `script-${projectId}` };
  const choose = useMutation({ ...chooseTakeMutation(), scope, onSuccess: settle, onError: fail });
  const align = useMutation({ ...alignScriptMutation(), scope, onSuccess: settle, onError: fail });
  const remove = useMutation({
    ...deleteScriptMutation(),
    onSuccess: () => qc.removeQueries({ queryKey: key }),
    onError: fail,
  });
  const build = useMutation({
    ...createScriptAssemblyMutation(),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: listTimelinesQueryKey({ path: { project_id: projectId } }) });
      void navigate(`/timeline/${t.id}`);
    },
    onError: fail,
  });
  const a = doc.alignment;
  // Dialogue lines are numbered 1, 2, 3 ... (scene headings and action are not).
  const numbers: number[] = [];
  for (const line of doc.lines) numbers.push((numbers.at(-1) ?? 0) + (line.kind === "dialogue" ? 1 : 0));
  if (replacing) return <UploadForm projectId={projectId} onCancel={() => setReplacing(false)} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">{doc.name}</h2>
          <p role="status" aria-label="Script summary" className="text-sm text-neutral-400">
            {doc.with_take} of {doc.dialogue_lines} dialogue lines have a take · compared by{" "}
            {scoredBy(a)} · match limit{" "}
            {doc.min_score} · {a.segments} transcript lines searched
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <button className="rounded bg-blue-600 px-3 py-1.5 font-medium disabled:opacity-50" disabled={build.isPending || doc.with_take === 0} onClick={() => build.mutate({ path: { project_id: projectId }, body: {} })}>
            {build.isPending ? "Building…" : "Build script assembly"}
          </button>
          <button className="rounded bg-neutral-800 px-3 py-1.5" disabled={align.isPending} onClick={() => align.mutate({ path: { project_id: projectId } })}>
            {align.isPending ? "Searching…" : "Find the lines again"}
          </button>
          <button
            className="rounded bg-neutral-800 px-3 py-1.5"
            onClick={() => {
              if (window.confirm("Replace the script? Takes you chose are kept only for lines that stay the same (same character, same words).")) setReplacing(true);
            }}
          >
            Replace script
          </button>
          <button
            className="rounded bg-neutral-800 px-3 py-1.5 hover:text-red-400"
            onClick={() => {
              if (window.confirm(`Delete the script “${doc.name}”? Timelines built from it stay.`)) remove.mutate({ path: { project_id: projectId } });
            }}
          >
            Delete
          </button>
        </div>
      </div>
      <ol aria-label="Script lines" className="space-y-2">
        {doc.lines.map((line, i) => (
          <ScriptLineRow
            key={line.id}
            line={line}
            number={numbers[i] ?? 0}
            busy={choose.isPending}
            onChoose={(body) => choose.mutate({ path: { line_id: line.id }, body })}
          />
        ))}
      </ol>
    </div>
  );
}

function Script({ projectId }: { projectId: string }) {
  const { data, error, isPending, refetch } = useQuery({ ...getScriptOptions({ path: { project_id: projectId } }), retry: false });
  const missing = (error as { code?: string } | null)?.code === "not_found";
  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Script</h1>
        <p className="text-sm text-neutral-400">
          Add the screenplay and CineMind finds where each line was said in your footage, with every take it found. Choose
          takes, then build a script-ordered assembly: an AI-assisted rough cut for you to edit.
        </p>
      </div>
      {isPending && <Loading label="Loading the script…" />}
      {missing && <UploadForm projectId={projectId} />}
      {error && !missing && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data && <Lines doc={data} projectId={projectId} />}
    </section>
  );
}
