import { exportTimeline } from "../api";
import { errorMessage } from "./errors";
import { toast } from "./toast";

/** Labels of the export formats the backend offers. */
export const EXPORT_FORMATS: Record<string, string> = {
  fcp7xml: "FCP7 XML (DaVinci Resolve)",
  edl: "EDL",
  otio: "OTIO",
  srt: "SRT subtitles",
};

/** Fetch the export and hand it to the browser as a file, so a failure (timeline deleted
 * elsewhere, format not possible, disk full) is shown instead of a broken download. */
export async function downloadExport(timelineId: string, fmt: string) {
  try {
    const { data, error, response } = await exportTimeline({ path: { timeline_id: timelineId, fmt }, parseAs: "blob" });
    if (error || !(data instanceof Blob) || !response?.ok) {
      toast.error(errorMessage(error));
      return;
    }
    const header = response.headers.get("content-disposition") ?? "";
    const encoded = /filename\*=utf-8''([^;]+)/i.exec(header)?.[1];
    const name = encoded ? decodeURIComponent(encoded) : (/filename="([^"]+)"/i.exec(header)?.[1] ?? `timeline.${fmt}`);
    const url = URL.createObjectURL(data);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0); // revoking at once can cancel the download
  } catch (e) {
    toast.error(errorMessage(e));
  }
}
