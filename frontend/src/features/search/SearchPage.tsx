import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { searchShots, type SearchOut } from "../../api";
import { judgeSearchResultMutation, searchByImageMutation } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { FUSION_NOTE, LIST_LABEL } from "./labels";
import { ResultCard } from "./ResultCard";
import { SearchFilters, type FilterValues } from "./SearchFilters";

export function SearchPage() {
  const projectId = useCurrentProject((s) => s.id);
  if (!projectId) {
    return (
      <EmptyState title="No project selected">
        <Link className="underline" to="/projects">
          Create or open a project
        </Link>{" "}
        to search its footage.
      </EmptyState>
    );
  }
  return <Search projectId={projectId} />;
}

function readFilters(params: URLSearchParams): FilterValues {
  const quality = params.get("minq");
  return {
    media_id: params.get("clip") ?? undefined,
    actor_id: params.get("actor") ?? undefined,
    scene_id: params.get("scene") ?? undefined,
    min_quality: quality && Number.isFinite(Number(quality)) ? Number(quality) : undefined,
    has_dialogue: params.get("talk") === "1",
  };
}

function writeParams(base: Record<string, string>, f: FilterValues): Record<string, string> {
  const out = { ...base };
  if (f.media_id) out.clip = f.media_id;
  if (f.actor_id) out.actor = f.actor_id;
  if (f.scene_id) out.scene = f.scene_id;
  if (f.min_quality != null) out.minq = String(f.min_quality);
  if (f.has_dialogue) out.talk = "1";
  return out;
}

function Summary({ data }: { data: SearchOut }) {
  const lists = Object.entries(data.lists).map(([name, n]) => `${LIST_LABEL[name] ?? name} ${n}`);
  return (
    <div className="space-y-1 text-xs text-neutral-400">
      <p role="status">
        {data.results.length} {data.results.length === 1 ? "shot" : "shots"}
        {data.like_shot_id ? " that look like the chosen shot" : ""}. Found per list: {lists.join(" · ") || "none"}.
      </p>
      {Object.entries(data.unavailable).map(([name, why]) => (
        <p key={name} role="alert" className="rounded border border-amber-800 bg-amber-950 p-2 text-amber-200">
          {LIST_LABEL[name] ?? name}: {why}
        </p>
      ))}
      <p>
        {FUSION_NOTE} (k = {data.rrf_k}
        {Object.values(data.weights).some((w) => w !== 1) &&
          `; each list's share is multiplied by its weight: ${Object.entries(data.weights)
            .map(([n, w]) => `${LIST_LABEL[n] ?? n} ${w}`)
            .join(", ")}`}
        )
      </p>
    </div>
  );
}

function Search({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = params.get("q")?.trim() ?? "";
  const like = params.get("like") ?? "";
  const filters = readFilters(params);
  const [draft, setDraft] = useState(q);
  const [pictureResult, setPictureResult] = useState<SearchOut | null>(null);
  const key = ["searchShots", projectId, q, like, filters] as const;
  const { data, error, isFetching } = useQuery({
    queryKey: key,
    enabled: !!(q || like) && !pictureResult,
    queryFn: async () => {
      const body = like ? { like_shot_id: like, filters } : { q, filters };
      const res = await searchShots({ path: { project_id: projectId }, body, throwOnError: true });
      return res.data;
    },
  });
  const picture = useMutation({
    ...searchByImageMutation(),
    onSuccess: (out) => setPictureResult(out),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const judge = useMutation({
    ...judgeSearchResultMutation(),
    // Patch the mark into the results shown; searching again would only cost time.
    onSuccess: (out) =>
      qc.setQueryData<SearchOut>(key, (old) =>
        old ? { ...old, results: old.results.map((r) => (r.shot_id === out.shot_id ? { ...r, relevant: out.relevant } : r)) } : old,
      ),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const go = (base: Record<string, string>, f: FilterValues = filters) => {
    setPictureResult(null);
    setParams(writeParams(base, f));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go(draft.trim() ? { q: draft.trim() } : {});
  };
  const searchPicture = (file: File | undefined) => {
    if (!file) return;
    picture.mutate({ path: { project_id: projectId }, query: filters, body: file });
  };
  const shown = pictureResult ?? data;
  const base: Record<string, string> = like ? { like } : q ? { q } : {};

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Search</h1>
        <p className="text-sm text-neutral-400">
          Describe a shot (“person walking in a forest”), a spoken word, a tag or a name; or use a picture. Everything runs on this
          machine. Results are suggestions ranked by several signals, explained on every card.
        </p>
      </div>
      <form role="search" className="flex flex-wrap gap-2" onSubmit={submit}>
        <input
          type="search"
          aria-label="Search shots"
          placeholder="What are you looking for?"
          maxLength={200}
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="rounded bg-blue-600 px-3 py-1.5 text-sm">Search</button>
        <label className="cursor-pointer rounded bg-neutral-800 px-3 py-1.5 text-sm">
          Search by picture
          <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" aria-label="Search by picture" onChange={(e) => searchPicture(e.target.files?.[0])} />
        </label>
      </form>
      <SearchFilters projectId={projectId} value={filters} onChange={(f) => go(base, f)} />
      {(isFetching || picture.isPending) && <Loading label="Searching…" />}
      {error && <ErrorState message={errorMessage(error)} />}
      {shown && (
        <>
          <Summary data={shown} />
          {shown.results.length === 0 ? (
            <p className="text-sm text-neutral-400">Nothing found. Try other words, or remove a filter.</p>
          ) : (
            <ol aria-label="Search results" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {shown.results.map((r) => (
                <ResultCard
                  key={r.shot_id}
                  result={r}
                  onMoreLike={(shot) => go({ like: shot })}
                  onJudge={shown.query ? (shot, relevant) => judge.mutate({ path: { project_id: projectId }, body: { query: shown.query ?? "", shot_id: shot, relevant } }) : undefined}
                />
              ))}
            </ol>
          )}
          {shown.query && (
            <p className="text-xs text-neutral-500">
              ✓ / ✕ mark whether a result fits “{shown.query}”. These marks are only used to measure how good search is (eval/search_eval.py); they do
              not change the order.
            </p>
          )}
        </>
      )}
    </section>
  );
}
