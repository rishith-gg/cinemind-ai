import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import type { ImportResponse } from "../../api";
import { importMediaMutation } from "../../api/@tanstack/react-query.gen";
import { toast } from "../../lib/toast";
import { FolderBrowser } from "./FolderBrowser";
import { UploadBox } from "./UploadBox";

type Mode = "reference" | "copy";

/** Summarise a batch for the toast: friendly counts, never silent about failures. */
export function summarize(items: ImportResponse["items"]): string {
  const added = items.filter((i) => i.media && !i.duplicate && !i.error_code).length;
  const dup = items.filter((i) => i.duplicate).length;
  const failed = items.filter((i) => i.error_code);
  let text = `Imported ${added} file${added === 1 ? "" : "s"}`;
  if (dup) text += `, ${dup} already in the project`;
  if (failed.length) text += `, ${failed.length} could not be imported (${failed[0]?.error_message ?? "unknown error"})`;
  return text + ".";
}

export function ImportPanel({ projectId, onImported }: { projectId: string; onImported: () => void }) {
  const [tab, setTab] = useState<"folder" | "upload">("folder");
  const [mode, setMode] = useState<Mode>("reference");
  const importMedia = useMutation({
    ...importMediaMutation(),
    onSuccess: (res) => {
      toast.info(summarize(res.items));
      onImported();
    },
  });

  return (
    <div className="space-y-3 rounded border border-neutral-800 bg-neutral-900 p-4">
      <div role="tablist" className="flex gap-2 text-sm">
        {(["folder", "upload"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`rounded px-3 py-1 ${tab === t ? "bg-neutral-700" : "bg-neutral-800/50"}`}
            onClick={() => setTab(t)}
          >
            {t === "folder" ? "Media folder" : "Upload"}
          </button>
        ))}
      </div>
      {tab === "folder" ? (
        <>
          <fieldset className="flex gap-4 text-sm">
            <legend className="sr-only">Import mode</legend>
            <label className="flex items-center gap-1">
              <input type="radio" checked={mode === "reference"} onChange={() => setMode("reference")} />
              Reference in place (no copy)
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" checked={mode === "copy"} onChange={() => setMode("copy")} />
              Copy into the project
            </label>
          </fieldset>
          <FolderBrowser
            busy={importMedia.isPending}
            onImport={(paths) => importMedia.mutate({ path: { project_id: projectId }, body: { paths, mode } })}
          />
        </>
      ) : (
        <UploadBox projectId={projectId} onDone={onImported} />
      )}
    </div>
  );
}
