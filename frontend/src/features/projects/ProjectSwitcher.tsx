import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate } from "react-router";

import { listProjectsOptions } from "../../api/@tanstack/react-query.gen";
import { useCurrentProject } from "../../lib/currentProject";

export function ProjectSwitcher() {
  const { data, error } = useQuery(listProjectsOptions());
  const { id, set } = useCurrentProject();
  const navigate = useNavigate();
  const projects = data ?? [];
  const loaded = data !== undefined;
  const known = projects.some((p) => p.id === id);
  useEffect(() => {
    if (loaded && id && !known) set(null); // stored project no longer exists
  }, [loaded, id, known, set]);
  const value = projects.some((p) => p.id === id) ? (id ?? "") : "";

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-neutral-400">Project</span>
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1"
        value={value}
        disabled={!!error}
        onChange={(e) => {
          if (e.target.value) {
            set(e.target.value);
            void navigate(`/projects/${e.target.value}`);
          } else set(null);
        }}
      >
        <option value="">
          {error ? "Can't load projects" : projects.length ? "Select a project…" : "No projects yet"}
        </option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}
