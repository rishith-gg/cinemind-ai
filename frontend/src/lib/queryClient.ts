import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { errorMessage } from "./errors";
import { toast } from "./toast";

/** Every failed mutation shows a toast; queries show errors inline, but background refetch
 * failures (data already on screen) are surfaced here too. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { // Retry once for network blips, never for answers the backend gave us (404, 422, ...).
        retry: (count, err) => count < 1 && !(err && typeof err === "object" && "code" in err),
        refetchOnWindowFocus: false } },
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.state.data !== undefined) toast.error(errorMessage(error));
      },
    }),
    mutationCache: new MutationCache({ onError: (error) => toast.error(errorMessage(error)) }),
  });
}
