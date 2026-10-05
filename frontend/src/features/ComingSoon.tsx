import { EmptyState } from "../components/states";

/** Honest placeholder for screens whose feature does not exist yet. */
export function ComingSoon({ title, phase }: { title: string; phase: number }) {
  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">{title}</h1>
      <EmptyState title="Not available yet">This screen is built in Phase {phase}.</EmptyState>
    </section>
  );
}
