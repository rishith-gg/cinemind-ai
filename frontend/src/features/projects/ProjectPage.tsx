import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams } from "react-router";

import { getProjectOptions } from "../../api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { data, error, isPending, refetch } = useQuery(getProjectOptions({ path: { project_id: projectId } }));

  const setCurrent = useCurrentProject((s) => s.set);
  const loadedId = data?.id;
  const notFound = !!error && typeof error === "object" && (error as { code?: string }).code === "not_found";
  useEffect(() => {
    if (loadedId) setCurrent(loadedId); // opening/reloading a project URL selects it in the switcher
    else if (notFound && useCurrentProject.getState().id === projectId) setCurrent(null);
  }, [loadedId, notFound, projectId, setCurrent]);

  if (isPending) return <Loading label="Loading project…" />;
  if (error || !data) {
    return (
      <div className="space-y-3">
        <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />
        <Link className="text-sm underline" to="/projects">
          Back to projects
        </Link>
      </div>
    );
  }
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{data.name}</h1>
      {data.description && <p className="text-neutral-400">{data.description}</p>}
      <Link className="inline-block rounded bg-blue-600 px-4 py-2 text-sm font-medium" to="/library">
        Open library
      </Link>
    </section>
  );
}
