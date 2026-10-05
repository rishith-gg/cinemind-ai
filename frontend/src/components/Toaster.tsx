import { useToasts } from "../lib/toast";

const STYLE = {
  error: "border-red-800 bg-red-950 text-red-100",
  success: "border-green-800 bg-green-950 text-green-100",
  info: "border-neutral-700 bg-neutral-900 text-neutral-100",
} as const;

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role={t.kind === "error" ? "alert" : "status"} className={`rounded border p-3 text-sm ${STYLE[t.kind]}`}>
          <div className="flex items-start justify-between gap-3">
            <span>{t.message}</span>
            <button aria-label="Dismiss" className="text-neutral-400 hover:text-white" onClick={() => dismiss(t.id)}>
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
