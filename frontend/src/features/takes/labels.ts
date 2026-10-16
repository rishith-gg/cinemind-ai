import type { TakeGroupOut, TakePairOut } from "../../api";

/** Plain names of the best-take signals, in the order they are shown. */
export const SIGNALS: [key: string, label: string, help: string][] = [
  ["focus", "Focus", "Sharpness sub-score of the shot's technical quality"],
  ["exposure", "Exposure", "Exposure sub-score of the shot's technical quality"],
  ["audio", "Audio", "Audio score of the clip (loudness, clipping, silence)"],
  ["complete", "Complete", "Share of the most typical take's words said here, in order"],
  ["clean", "Clean", "1 minus 0.25 per flub (repeat, filler, unclear line) and 0.5 per cut-off edge"],
];

export function bestByText(group: TakeGroupOut): string {
  if (group.best_by === "you") return "Best take chosen by you";
  if (group.best_by === "none") return "No best take: every take is rejected";
  return "Best take suggested from its signals";
}

/** One line on why two takes were put together (or not). */
export function pairText(p: TakePairOut): string {
  const parts = [p.why];
  if (p.text !== null && p.text !== undefined) parts.push(`words ${p.text.toFixed(2)}`);
  if (p.picture !== null && p.picture !== undefined) parts.push(`picture ${p.picture.toFixed(2)}`);
  parts.push(`neighbours ${p.adjacent.toFixed(2)}`, `pair score ${p.score.toFixed(2)}`);
  return parts.join(" · ");
}
