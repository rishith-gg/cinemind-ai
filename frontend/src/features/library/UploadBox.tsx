import { useState } from "react";

import { uploadMedia } from "../../api";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";

/** Drag-and-drop / file picker. Files are streamed to the backend one at a time. */
export function UploadBox({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  const upload = async (files: File[]) => {
    for (const file of files) {
      setBusy(file.name);
      try {
        const res = await uploadMedia({
          path: { project_id: projectId },
          query: { filename: file.name },
          body: file,
        });
        if (res.error) toast.error(`${file.name}: ${errorMessage(res.error)}`);
        else if (res.data.duplicate) toast.info(`${file.name} is already in this project.`);
        else toast.success(`Uploaded ${file.name}.`);
      } catch (err) {
        toast.error(`${file.name}: ${errorMessage(err)}`); // e.g. backend not reachable
      }
    }
    setBusy(null);
    onDone();
  };

  return (
    <div
      className="rounded border border-dashed border-neutral-600 p-6 text-center text-sm"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        void upload(Array.from(e.dataTransfer.files));
      }}
    >
      <p className="mb-2 text-neutral-300">Drop video or audio files here, or choose them.</p>
      <input
        type="file"
        multiple
        accept="video/*,audio/*,.mkv,.mxf,.mov"
        aria-label="Choose files to upload"
        disabled={busy !== null}
        onChange={(e) => {
          void upload(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      {busy && <p role="status" className="mt-2 text-neutral-400">Uploading {busy}…</p>}
      <p className="mt-2 text-xs text-neutral-500">For large footage, use a media folder instead (no copy needed).</p>
    </div>
  );
}
