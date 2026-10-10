import type { TranscriptOut } from "../../api";

/** "en" -> "English". Falls back to the code for anything the browser does not know. */
export function languageName(code: string | null | undefined): string {
  if (!code) return "unknown";
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export const STATUS_LABEL: Record<TranscriptOut["status"], string> = {
  pending: "Not transcribed yet",
  done: "Transcribed",
  no_speech: "No speech found",
  no_audio: "No audio track",
  model_missing: "Speech model not downloaded",
  audio_unreadable: "Audio not readable",
};

export const UNCERTAIN_HINT =
  "The speech model did not accept its own result for this part (low likelihood or repetitive text). Treat it as a guess.";
