import { useQueryClient } from "@tanstack/react-query";

import type { ScenesOut } from "../../api";
import { listScenesQueryKey } from "../../api/@tanstack/react-query.gen";

/** Keeps the scene list in step with what an edit returned (every edit returns the new list). */
export function useSetScenes(projectId: string): (data: ScenesOut) => void {
  const qc = useQueryClient();
  return (data) => qc.setQueryData(listScenesQueryKey({ path: { project_id: projectId } }), data);
}
