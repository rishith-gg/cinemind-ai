import { HealthPanel } from "./HealthPanel";

export function SettingsPage() {
  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <h2 className="text-sm font-medium text-neutral-400">System check</h2>
      <HealthPanel />
    </section>
  );
}
