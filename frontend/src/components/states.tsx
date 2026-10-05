import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="p-6 text-sm text-neutral-400">
      {label}
    </p>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-neutral-700 p-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-neutral-400">{children}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded border border-red-800 bg-red-950 p-4">
      <p className="font-medium">{message}</p>
      {onRetry && (
        <button className="mt-3 rounded bg-neutral-800 px-3 py-1 text-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
