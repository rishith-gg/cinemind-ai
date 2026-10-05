/** Turn anything thrown by the generated client into a plain-language message. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object") {
    const e = error as { message?: unknown; detail?: unknown };
    if (typeof e.message === "string" && "code" in error) return e.message; // backend DomainError
    if (Array.isArray(e.detail)) return "Some of the values you entered are not valid.";
    if (error instanceof TypeError) return "Can't reach the CineMind backend. Is `cinemind serve` running?";
  }
  return "Something went wrong. Please try again.";
}
