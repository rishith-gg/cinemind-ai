import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { listProjectsOptions } from "../api/@tanstack/react-query.gen";
import { errorMessage } from "../lib/errors";
import { EmptyState, ErrorState, Loading } from "../components/states";

export function DashboardPage() {
  const { data, error, isPending, refetch } = useQuery(listProjectsOptions());
  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      {isPending && <Loading />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data && (
        <p className="text-neutral-300">
          {data.length} project{data.length === 1 ? "" : "s"}
        </p>
      )}
      <EmptyState title="Footage statistics appear here once you import clips (Phase 3).">
        <Link className="underline" to="/projects">
          Go to projects
        </Link>
      </EmptyState>
    </section>
  );
}
