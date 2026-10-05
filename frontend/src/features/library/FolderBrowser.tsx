import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { browseFolderOptions } from "../../api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "../../components/states";
import { errorMessage } from "../../lib/errors";
import { formatBytes } from "./format";

/** Server-side folder browser, limited by the backend to the approved media roots. */
export function FolderBrowser({ onImport, busy }: { onImport: (paths: string[]) => void; busy: boolean }) {
  const [path, setPath] = useState<string | undefined>(undefined);
  const [picked, setPicked] = useState<string[]>([]);
  const { data, error, isPending, refetch } = useQuery(browseFolderOptions({ query: { path } }));

  const go = (p: string | undefined) => {
    setPicked([]);
    setPath(p);
  };
  const toggle = (p: string) => setPicked((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));

  if (isPending) return <Loading label="Reading folder…" />;
  if (error || !data) return <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />;
  if (data.roots.length === 0) {
    return (
      <p role="status" className="text-sm text-neutral-300">
        No media folders are approved yet. Add your footage folder to <code>media_roots</code> in{" "}
        <code>cinemind.toml</code> (for example <code>media_roots = ["/Users/me/Footage"]</code>), restart CineMind, or
        use the Upload tab for small files.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-neutral-400">{data.path ?? "Approved media folders"}</p>
      {data.path && (
        <button className="text-sm underline" onClick={() => go(data.parent ?? undefined)}>
          ↑ Up
        </button>
      )}
      <ul className="max-h-72 divide-y divide-neutral-800 overflow-auto rounded border border-neutral-800">
        {data.entries.map((e) => (
          <li key={e.path} className="flex items-center gap-2 px-3 py-1.5 text-sm">
            {e.is_dir ? (
              <>
                <input type="checkbox" aria-label={`Select folder ${e.name}`} checked={picked.includes(e.path)} onChange={() => toggle(e.path)} />
                <button className="flex-1 text-left hover:underline" onClick={() => go(e.path)}>
                  📁 {e.name}
                </button>
              </>
            ) : (
              <>
                <input type="checkbox" aria-label={`Select ${e.name}`} checked={picked.includes(e.path)} onChange={() => toggle(e.path)} />
                <span className={`flex-1 ${e.is_media_candidate ? "" : "text-neutral-500"}`}>{e.name}</span>
                <span className="text-xs text-neutral-500">{formatBytes(e.size_bytes ?? 0)}</span>
              </>
            )}
          </li>
        ))}
        {data.entries.length === 0 && <li className="px-3 py-2 text-sm text-neutral-500">This folder is empty.</li>}
      </ul>
      <div className="flex gap-2">
        <button
          className="rounded bg-blue-600 px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={busy || picked.length === 0}
          onClick={() => {
            onImport(picked);
            setPicked([]);
          }}
        >
          Import selected ({picked.length})
        </button>
        {data.path && (
          <button
            className="rounded bg-neutral-800 px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={busy}
            onClick={() => onImport([data.path as string])}
          >
            Import this whole folder
          </button>
        )}
      </div>
    </div>
  );
}
