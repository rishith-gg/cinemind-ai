import type { ListHit } from "../../api";

export const LIST_LABEL: Record<string, string> = {
  keyword: "Spoken words",
  labels: "Labels",
  text: "Meaning of speech",
  visual: "Picture",
};

/** One line per list for "why this result". */
export function whyLine(name: string, hit: ListHit): string {
  const rank = `#${hit.rank}`;
  if (name === "keyword") return `${LIST_LABEL.keyword} ${rank} (BM25 ${hit.score.toFixed(2)})`;
  if (name === "labels") return `${LIST_LABEL.labels} ${rank}: ${hit.matched.join(", ")}`;
  return `${LIST_LABEL[name] ?? name} ${rank} (similarity ${hit.score.toFixed(2)})`;
}

export const FUSION_NOTE =
  "Each list ranks shots its own way; the order here adds 1 / (k + rank) from every list a shot is in (Reciprocal Rank Fusion). The score only orders results, it is not a probability.";
