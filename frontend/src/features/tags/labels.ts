import type { TagOut } from "../../api";

interface Evaluation {
  dataset?: string;
  precision?: number;
  precision_ci95?: number[];
  recall?: number;
  reason?: string;
}

const pct = (n: number) => `${Math.round(n * 100)}%`;

/** Why a model tag is not shown, in plain words. */
export function hiddenReason(tag: TagOut): string {
  if (tag.review === "rejected") return "rejected by you";
  const evaluation = (tag.details.evaluation ?? {}) as Evaluation;
  switch (tag.status) {
    case "below":
      return `under its threshold (${tag.threshold == null ? "?" : tag.threshold.toFixed(2)}) on most keyframes`;
    case "disabled":
      return `switched off: ${evaluation.reason ?? "too often wrong on labelled photos"}`;
    case "not_evaluated":
      return "not evaluated (no labelled data to set a threshold)";
    default:
      return "";
  }
}

/** Tooltip: what produced the tag and how good its threshold was where it was measured. */
export function tagTitle(tag: TagOut): string {
  if (tag.source === "faces") return `${tag.label}: counted by the faces stage (${String(tag.details.rule ?? "")})`;
  if (tag.source === "transcript") return `${tag.label}: from the transcript (${String(tag.details.rule ?? "")})`;
  const evaluation = (tag.details.evaluation ?? {}) as Evaluation;
  const parts = [`${tag.group_label}: ${tag.label}`, `score ${tag.score == null ? "-" : tag.score.toFixed(2)}`];
  if (tag.threshold != null) parts.push(`threshold ${tag.threshold.toFixed(2)}`);
  if (evaluation.precision != null) {
    const [low, high] = evaluation.precision_ci95 ?? [];
    const ci = low != null && high != null ? ` (95% CI ${pct(low)}–${pct(high)})` : "";
    parts.push(`right ${pct(evaluation.precision)} of the time when shown on single ${evaluation.dataset ?? "labelled"} photos${ci}`);
  }
  const places = (tag.details.top_places as [string, number][][] | undefined)?.[0];
  if (places?.length) parts.push(`closest places (first keyframe): ${places.map(([name, p]) => `${name} ${p.toFixed(2)}`).join(", ")}`);
  if (tag.review) parts.push(`${tag.review} by you`);
  return parts.join(" · ");
}
