import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { searchByImage, searchShots, type SearchOut, type SearchResult } from "../../api";
import { judgeSearchResultMutation } from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { FUSION_NOTE, LIST_LABEL } from "./labels";
import { ResultCard } from "./ResultCard";
import { SearchFilters, type FilterValues } from "./SearchFilters";
import { WeightsPanel } from "./WeightsPanel";

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
    selects_only: params.get("sel") === "1",
    include_rejected: params.get("rej") === "1",
  };
}

function writeParams(base: Record<string, string>, f: FilterValues): Record<string, string> {
  const out = { ...base };
  if (f.media_id) out.clip = f.media_id;
  if (f.actor_id) out.actor = f.actor_id;
  if (f.scene_id) out.scene = f.scene_id;
  if (f.min_quality != null) out.minq = String(f.min_quality);
  if (f.has_dialogue) out.talk = "1";
  if (f.selects_only) out.sel = "1";
  if (f.include_rejected) out.rej = "1";
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
  // A picture search keeps its file, so it can follow the weights and filters like a typed one.
  const [picture, setPicture] = useState<File | null>(null);
  // What-if weights: the sliders move `draftWeights`; the search follows a moment later.
  const [draftWeights, setDraftWeights] = useState<Record<string, number> | null>(null);
  const [weights, setWeights] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setWeights(draftWeights), 250);
    return () => clearTimeout(timer);
  }, [draftWeights]);
  const pictureId = picture ? `${picture.name}:${picture.size}:${picture.lastModified}` : null;
  const key = ["searchShots", projectId, pictureId ?? q, pictureId ? "" : like, filters, weights] as const;
  const { data, error, isFetching } = useQuery({
    queryKey: key,
    enabled: !!(q || like || picture),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (picture) {
        const query = { ...filters, ...(weights ? { weights: JSON.stringify(weights) } : {}) };
        const res = await searchByImage({ path: { project_id: projectId }, query, body: picture, throwOnError: true });
        return res.data;
      }
      const body = { ...(like ? { like_shot_id: like } : { q }), filters, ...(weights ? { weights } : {}) };
      const res = await searchShots({ path: { project_id: projectId }, body, throwOnError: true });
      return res.data;
    },
  });
  // A mark or judgment is patched into every cached search of the project, not searched again.
  const patch = (shotId: string, change: Partial<SearchResult>) =>
    qc.setQueriesData<SearchOut>({ queryKey: ["searchShots", projectId] }, (old) =>
      old ? { ...old, results: old.results.map((r) => (r.shot_id === shotId ? { ...r, ...change } : r)) } : old,
    );
  const judge = useMutation({
    ...judgeSearchResultMutation(),
    onSuccess: (out) => patch(out.shot_id, { relevant: out.relevant }),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const go = (base: Record<string, string>, f: FilterValues = filters) => {
    setPicture(null);
    setParams(writeParams(base, f));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go(draft.trim() ? { q: draft.trim() } : {});
  };
  const searchPicture = (file: File | undefined) => {
    if (file) setPicture(file);
  };
  const shown = data;
  const defaults = data?.ranking_defaults ?? null;
  const describe = (shotId: string) => {
    const r = shown?.results.find((x) => x.shot_id === shotId);
    return r ? `${r.filename} shot ${r.shot_index + 1}` : "another shot";
  };
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
      <SearchFilters projectId={projectId} value={filters} onChange={(f) => (picture ? setParams(writeParams(base, f)) : go(base, f))} />
      {defaults && <WeightsPanel weights={draftWeights ?? defaults} defaults={defaults} onChange={(w) => setDraftWeights(w)} />}
      {isFetching && <Loading label="Searching…" />}
      {error && <ErrorState message={errorMessage(error)} />}
      {shown && (
        <>
          <Summary data={shown} />
          {shown.results.length === 0 ? (
            <p className="text-sm text-neutral-400">Nothing found. Try other words, or remove a filter.</p>
          ) : (
            <ol aria-label="Search results" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {shown.results.map((r, i) => (
                <ResultCard
                  key={r.shot_id}
                  result={r}
                  position={i + 1}
                  describe={describe}
                  onMarked={(out) => patch(out.shot_id, { mark: out.mark, stars: out.stars })}
                  onMoreLike={(shot) => go({ like: shot })}
                  onJudge={shown.query ? (shot, relevant) => judge.mutate({ path: { project_id: projectId }, body: { query: shown.query ?? "", shot_id: shot, relevant } }) : undefined}
                />
              ))}
            </ol>
          )}
          {shown.query && (
            <p className="text-xs text-neutral-500">
              ✓ / ✕ mark whether a result fits “{shown.query}”; they are only used to measure how good search is (eval/search_eval.py). Select,
              Reject and stars are your verdict on the shot itself: rejected shots are left out of search, selected and starred ones rank higher.
            </p>
          )}
        </>
      )}
    </section>
  );
}
