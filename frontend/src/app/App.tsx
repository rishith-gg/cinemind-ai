import { Navigate, Route, Routes } from "react-router";

import { Layout } from "../components/Layout";
import { ComingSoon } from "../features/ComingSoon";
import { DashboardPage } from "../features/DashboardPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { SettingsPage } from "../features/system/SettingsPage";

const LATER = [
  { path: "library", title: "Library", phase: 3 },
  { path: "shots", title: "Shots / Scenes", phase: 4 },
  { path: "actors", title: "Actors", phase: 7 },
  { path: "transcripts", title: "Transcripts", phase: 6 },
  { path: "search", title: "Search", phase: 9 },
  { path: "timeline", title: "Timeline", phase: 11 },
  { path: "export", title: "Export", phase: 4 },
];

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="settings" element={<SettingsPage />} />
        {LATER.map((l) => (
          <Route key={l.path} path={l.path} element={<ComingSoon title={l.title} phase={l.phase} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
