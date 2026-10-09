import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";

import {
  deleteMediaMutation,
  getMediaOptions,
  getMediaQueryKey,
  processMediaMutation,
} from "../../api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "../../components/states";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { QualityPanel } from "../quality/QualityPanel";
import { mediaStatus } from "./format";
import { StatusBadge } from "./MediaCard";
import { MetadataPanel } from "./MetadataPanel";
import { Player } from "./Player";

export function ClipPage() {
  const { mediaId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, error, isPending, refetch } = useQuery(getMediaOptions({ path: { media_id: mediaId } }));
  const reprocess = useMutation({
    ...processMediaMutation(),
    onSuccess: () => {
      toast.info("Reprocessing queued.");
      void qc.invalidateQueries({ queryKey: getMediaQueryKey({ path: { media_id: mediaId } }) });
    },
  });
  const remove = useMutation({
    ...deleteMediaMutation(),
    onSuccess: () => {
      toast.info("Removed from the project. The original file was not touched.");
      void navigate("/library");
    },
  });

  if (isPending) return <Loading label="Loading clip…" />;
  if (error || !data) {
    return (
      <div className="space-y-3">
        <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />
        <Link className="text-sm underline" to="/library">
          Back to library
        </Link>
      </div>
    );
  }
  const status = mediaStatus(data);
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <Link className="text-sm text-neutral-400 underline" to="/library">
            ← Library
          </Link>
          <h1 className="truncate text-xl font-semibold">{data.filename}</h1>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge media={data} />
          <button className="rounded bg-neutral-800 px-3 py-1.5 text-sm" onClick={() => reprocess.mutate({ path: { media_id: data.id } })}>
            Reprocess
          </button>
          <button
            className="rounded bg-neutral-800 px-3 py-1.5 text-sm hover:text-red-400"
            onClick={() => {
              if (window.confirm("Remove this clip from the project? The original file is never deleted."))
                remove.mutate({ path: { media_id: data.id } });
            }}
          >
            Remove
          </button>
        </div>
      </div>
      {data.source_missing && (
        <div role="alert" className="rounded border border-amber-800 bg-amber-950 p-3 text-sm">
          The original file is missing or was moved{data.has_proxy ? "; the proxy still plays" : ""}. Put it back at{" "}
          <code>{data.path}</code> and reprocess.
        </div>
      )}
      {status === "failed" && (
        <div role="alert" className="rounded border border-red-800 bg-red-950 p-3 text-sm">
          {data.job?.error_message ?? "Processing failed."} You can fix the file and press Reprocess.
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        {data.has_proxy ? (
          <Player media={data} />
        ) : (
          <p className="rounded border border-dashed border-neutral-700 p-8 text-center text-sm text-neutral-400">
            {status === "failed" ? "No playable proxy was created." : "The proxy is still being created. This page updates by itself."}
          </p>
        )}
        <div className="space-y-6">
          <QualityPanel mediaId={data.id} />
          <MetadataPanel media={data} />
        </div>
      </div>
    </section>
  );
}
