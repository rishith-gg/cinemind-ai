import { HealthPanel } from "../features/system/HealthPanel";

export function App() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">CineMind AI</h1>
      <p className="mb-6 text-sm text-neutral-400">AI-assisted pre-editing. Phase 0: backend connection check.</p>
      <HealthPanel />
    </main>
  );
}
