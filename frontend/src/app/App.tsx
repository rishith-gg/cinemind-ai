import { Navigate, Route, Routes } from "react-router";

import { Layout } from "../components/Layout";
import { ActorPage } from "../features/actors/ActorPage";
import { ActorsPage } from "../features/actors/ActorsPage";
import { DashboardPage } from "../features/DashboardPage";
import { ExportPage } from "../features/export/ExportPage";
import { ClipPage } from "../features/library/ClipPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { ShotsPage } from "../features/shots/ShotsPage";
import { SettingsPage } from "../features/system/SettingsPage";
import { SearchPage } from "../features/search/SearchPage";
import { TimelineEditorPage } from "../features/timeline/TimelineEditor";
import { TimelinePage } from "../features/timeline/TimelinePage";
import { TranscriptsPage } from "../features/transcripts/TranscriptsPage";

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
        <Route path="search" element={<SearchPage />} />
        <Route path="transcripts" element={<TranscriptsPage />} />
        <Route path="actors" element={<ActorsPage />} />
        <Route path="actors/:actorId" element={<ActorPage />} />
        <Route path="timeline" element={<TimelinePage />} />
        <Route path="timeline/:timelineId" element={<TimelineEditorPage />} />
        <Route path="export" element={<ExportPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
