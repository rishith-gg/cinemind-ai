import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { SpeechLanguagesOut } from "../../api";
import { getSpeechLanguagesQueryKey, getSpeechLanguagesOptions, setSpeechLanguagesMutation } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { languageName } from "./labels";

interface Draft {
  languages: string[];
  detect_only: string[];
}

function Editor({ projectId, saved }: { projectId: string; saved: SpeechLanguagesOut }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>({ languages: saved.languages, detect_only: saved.detect_only });
  const save = useMutation({
    ...setSpeechLanguagesMutation(),
    onSuccess: (out) => {
      qc.setQueryData(getSpeechLanguagesQueryKey({ path: { project_id: projectId } }), out);
      toast.info(`Saved. ${out.queued} clips queued; only their transcripts are made again.`);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const changed = JSON.stringify(draft) !== JSON.stringify({ languages: saved.languages, detect_only: saved.detect_only });
  const add = (code: string) => code && setDraft((d) => ({ ...d, languages: [...d.languages, code] }));
  const remove = (code: string) => setDraft((d) => ({ languages: d.languages.filter((c) => c !== code), detect_only: d.detect_only.filter((c) => c !== code) }));
  const toggleWrite = (code: string, write: boolean) =>
    setDraft((d) => ({ ...d, detect_only: write ? d.detect_only.filter((c) => c !== code) : [...d.detect_only, code] }));
  const addable = saved.available.filter((c) => !draft.languages.includes(c)).sort((a, b) => languageName(a).localeCompare(languageName(b)));
  return (
    <section aria-label="Spoken languages" className="space-y-2 rounded border border-neutral-800 p-3 text-sm">
      <h2 className="font-medium">Spoken languages</h2>
      <p className="text-xs text-neutral-400">
        The language of each clip is detected among these (none chosen = any language). Untick “write transcript” for a language the
        speech model writes too poorly to be useful: its clips then show that they have speech in that language, and no text.
      </p>
      {draft.languages.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {draft.languages.map((code) => (
            <li key={code} className="flex items-center gap-2 rounded border border-neutral-700 px-2 py-1">
              <span>{languageName(code)}</span>
              <label className="flex items-center gap-1 text-xs text-neutral-400">
                <input
                  type="checkbox"
                  checked={!draft.detect_only.includes(code)}
                  onChange={(e) => toggleWrite(code, e.target.checked)}
                  aria-label={`Write transcripts in ${languageName(code)}`}
                />
                write transcript
              </label>
              <button className="text-xs text-neutral-400 hover:text-red-300" aria-label={`Remove ${languageName(code)}`} onClick={() => remove(code)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
          aria-label="Add a spoken language"
          value=""
          onChange={(e) => add(e.target.value)}
        >
          <option value="">Add a language…</option>
          {addable.map((code) => (
            <option key={code} value={code}>
              {languageName(code)}
            </option>
          ))}
        </select>
        <button
          className="rounded bg-blue-600 px-3 py-1 disabled:opacity-40"
          disabled={!changed || save.isPending}
          onClick={() => save.mutate({ path: { project_id: projectId }, body: draft })}
        >
          Save and transcribe again
        </button>
      </div>
    </section>
  );
}

/** The project's spoken languages, editable. Saving queues every clip again; only the
 * transcript (and what is made from it) is redone. */
export function SpokenLanguages({ projectId }: { projectId: string }) {
  const { data } = useQuery(getSpeechLanguagesOptions({ path: { project_id: projectId } }));
  if (!data) return null;
  return <Editor key={JSON.stringify([data.languages, data.detect_only])} projectId={projectId} saved={data} />;
}
