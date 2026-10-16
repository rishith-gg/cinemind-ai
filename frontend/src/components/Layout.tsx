import { NavLink, Outlet } from "react-router";

import { useJobEvents } from "../lib/useJobEvents";
import { ProjectSwitcher } from "../features/projects/ProjectSwitcher";
import { Toaster } from "./Toaster";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/projects", label: "Projects" },
  { to: "/library", label: "Library" },
  { to: "/shots", label: "Shots / Scenes" },
  { to: "/actors", label: "Actors" },
  { to: "/transcripts", label: "Transcripts" },
  { to: "/search", label: "Search" },
  { to: "/takes", label: "Takes" },
  { to: "/script", label: "Script" },
  { to: "/timeline", label: "Timeline" },
  { to: "/export", label: "Export" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const { connected } = useJobEvents();
  return (
    <div className="flex h-screen">
      <nav aria-label="Main" className="flex w-52 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900 p-3">
        <p className="mb-4 px-2 text-lg font-semibold">CineMind AI</p>
        <ul className="space-y-1">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `block rounded px-2 py-1.5 text-sm ${isActive ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-800/60"}`
                }
              >
                {n.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-neutral-800 px-6 py-3">
          <ProjectSwitcher />
          <span className="text-xs text-neutral-500">
            <span
              role="img"
              aria-label={connected ? "Live updates connected" : "Live updates disconnected"}
              className={connected ? "text-green-500" : "text-neutral-600"}
            >
              ●
            </span>{" "}
            AI-assisted pre-editing · local only
          </span>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  );
}
