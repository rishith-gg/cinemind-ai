import { Navigate, Route, Routes } from "react-router";

import { Layout } from "../components/Layout";
import { ComingSoon } from "../features/ComingSoon";
import { DashboardPage } from "../features/DashboardPage";
import { ExportPage } from "../features/export/ExportPage";
import { ClipPage } from "../features/library/ClipPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { ShotsPage } from "../features/shots/ShotsPage";
import { SettingsPage } from "../features/system/SettingsPage";

const LATER = [
  { path: "actors", title: "Actors", phase: 7 },
  { path: "transcripts", title: "Transcripts", phase: 6 },
  { path: "search", title: "Search", phase: 9 },
  { path: "timeline", title: "Timeline", phase: 11 },
];

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="library/:mediaId" element={<ClipPage />} />
        <Route path="shots" element={<ShotsPage />} />
        <Route path="export" element={<ExportPage />} />
        <Route path="settings" element={<SettingsPage />} />
        {LATER.map((l) => (
          <Route key={l.path} path={l.path} element={<ComingSoon title={l.title} phase={l.phase} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
