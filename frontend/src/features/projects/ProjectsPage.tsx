import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import {
  createProjectMutation,
  deleteProjectMutation,
  listProjectsOptions,
  listProjectsQueryKey,
} from "../../api/@tanstack/react-query.gen";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { useCurrentProject } from "../../lib/currentProject";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";

export function ProjectsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const setCurrent = useCurrentProject((s) => s.set);
  const [name, setName] = useState("");
  const { data, error, isPending, refetch } = useQuery(listProjectsOptions());

  const refresh = () => qc.invalidateQueries({ queryKey: listProjectsQueryKey() });
  const create = useMutation({
    ...createProjectMutation(),
    onSuccess: async (project) => {
      setName("");
      await refresh();
      setCurrent(project.id);
      toast.success(`Created project “${project.name}”.`);
      void navigate(`/projects/${project.id}`);
    },
  });
  const remove = useMutation({
    ...deleteProjectMutation(),
    onSuccess: (_d, vars) => {
      if (useCurrentProject.getState().id === vars.path.project_id) setCurrent(null);
      toast.info("Project deleted. Your source footage was not touched.");
    },
    onSettled: refresh, // also refresh after a 404 so a stale row disappears
  });

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Projects</h1>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate({ body: { name: name.trim() } });
        }}
      >
        <input
          aria-label="Project name"
          className="flex-1 rounded border border-neutral-700 bg-neutral-900 px-3 py-2"
          placeholder="New project name"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          className="rounded bg-blue-600 px-4 py-2 font-medium disabled:opacity-50"
          disabled={!name.trim() || create.isPending}
        >
          Create project
        </button>
      </form>

      {isPending && <Loading label="Loading projects…" />}
      {error && <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />}
      {data?.length === 0 && (
        <EmptyState title="No projects yet">Create one above to start organizing footage.</EmptyState>
      )}
      <ul className="divide-y divide-neutral-800 rounded border border-neutral-800 empty:hidden">
        {data?.map((p) => (
          <li key={p.id} className="flex items-center justify-between px-4 py-3">
            <Link to={`/projects/${p.id}`} onClick={() => setCurrent(p.id)} className="hover:underline">
              {p.name}
            </Link>
            <button
              className="text-sm text-neutral-400 hover:text-red-400"
              aria-label={`Delete ${p.name}`}
              onClick={() => {
                if (window.confirm(`Delete project “${p.name}”? Derived data is removed; source footage is never touched.`))
                  remove.mutate({ path: { project_id: p.id } });
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
