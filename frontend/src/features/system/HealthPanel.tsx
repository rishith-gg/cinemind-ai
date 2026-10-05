import { useQuery } from "@tanstack/react-query";

import { getHealthOptions } from "../../api/@tanstack/react-query.gen";

const STATUS_COLOR = { ok: "text-green-400", warn: "text-yellow-400", missing: "text-red-400" } as const;

export function HealthPanel() {
  // The query options come from the client generated from the backend's OpenAPI schema.
  const { data, error, isPending, refetch } = useQuery(getHealthOptions());

  if (isPending) return <p role="status">Contacting backend…</p>;

  if (error || !data) {
    return (
      <div role="alert" className="rounded border border-red-800 bg-red-950 p-4">
        <p className="font-medium">Can't reach the CineMind backend.</p>
        <p className="mt-1 text-sm">Start it with <code>uv run cinemind serve</code>, then retry.</p>
        <button className="mt-3 rounded bg-neutral-800 px-3 py-1" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    );
  }

  const { report } = data;
  return (
    <section className="space-y-4">
      <p>
        Backend: <strong data-testid="backend-status">{data.status}</strong> · v{data.version} · model tier:{" "}
        <strong>{report.selected_tier}</strong>
      </p>
      <p className="text-sm text-neutral-400">
        {report.hardware.cpu_name} · {report.hardware.ram_gb} GB RAM · GPU: {report.hardware.gpu.kind} —{" "}
        {report.recommended.reason}
      </p>
      <ul className="divide-y divide-neutral-800 rounded border border-neutral-800">
        {report.checks.map((c) => (
          <li key={c.name} className="flex justify-between px-3 py-2 text-sm">
            <span>{c.name}</span>
            <span className={STATUS_COLOR[c.status]}>
              {c.status}
              {c.version ? ` · ${c.version}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
