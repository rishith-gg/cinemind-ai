import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getMediaQueryKey, getSpeechLanguagesOptions, setClipSpeechLanguageMutation } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { languageName } from "./labels";

/** The language of this clip's speech: detected among the project's spoken languages, or set
 * by the user (the clip is then transcribed again in that language). */
export function ClipLanguage({ mediaId, projectId, value }: { mediaId: string; projectId: string; value: string | null }) {
  const qc = useQueryClient();
  const { data } = useQuery(getSpeechLanguagesOptions({ path: { project_id: projectId } }));
  const save = useMutation({
    ...setClipSpeechLanguageMutation(),
    onSuccess: (out) => {
      toast.info(out.language ? `Transcribing again in ${languageName(out.language)}.` : "Detecting the language again.");
      void qc.invalidateQueries({ queryKey: getMediaQueryKey({ path: { media_id: mediaId } }) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  if (!data) return null;
  const project = data.languages;
  const others = data.available.filter((code) => !project.includes(code)).sort((a, b) => languageName(a).localeCompare(languageName(b)));
  const label = (code: string) => `${languageName(code)}${data.detect_only.includes(code) ? " (detect only)" : ""}`;
  const detect = project.length ? `Detect among ${project.map(languageName).join(", ")}` : "Detect automatically";
  return (
    <label className="flex items-center gap-1 text-xs text-neutral-400">
      Language
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-neutral-200"
        value={value ?? ""}
        disabled={save.isPending}
        onChange={(e) => save.mutate({ path: { media_id: mediaId }, body: { language: e.target.value || null } })}
      >
        <option value="">{detect}</option>
        {project.map((code) => (
          <option key={code} value={code}>
            {label(code)}
          </option>
        ))}
        {others.length > 0 && (
          <optgroup label="Other languages">
            {others.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  );
}
