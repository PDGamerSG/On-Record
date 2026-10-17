import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import AppShell from "./components/shell/AppShell";
import AskDrawer from "./components/ask/AskDrawer";
import CommandPalette from "./components/CommandPalette";
import MeetingsPage from "./pages/MeetingsPage";
import MeetingRoom from "./pages/MeetingRoom";
import CommitmentsPage from "./pages/CommitmentsPage";
import DecisionsPage from "./pages/DecisionsPage";
import PeoplePage from "./pages/PeoplePage";
import GraphPage from "./pages/GraphPage";

// The landing page carries the 3D hero, so it loads in its own chunk and the app never pays for it.
const LandingPage = lazy(() => import("./landing/LandingPage"));

function AppLayout() {
  return (
    <>
      <AppShell>
        <Outlet />
      </AppShell>
      <AskDrawer />
      <CommandPalette />
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <Suspense fallback={<div className="landing-boot" />}>
              <LandingPage />
            </Suspense>
          }
        />
        <Route element={<AppLayout />}>
          <Route path="/meetings" element={<MeetingsPage />} />
          <Route path="/m/:id" element={<MeetingRoom />} />
          <Route path="/commitments" element={<CommitmentsPage />} />
          <Route path="/decisions" element={<DecisionsPage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/graph" element={<GraphPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
