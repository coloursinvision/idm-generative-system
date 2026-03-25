import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { AdvisorPanel } from "./components/advisor/AdvisorPanel";
import { ComposerPanel } from "./components/composer/ComposerPanel";
import { EffectsExplorer } from "./components/effects/EffectsExplorer";
import { GeneratorPanel } from "./components/generator/GeneratorPanel";
import { PO33Guide } from "./components/guide/PO33Guide";
import { EP133Guide } from "./components/guide/EP133Guide";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/advisor" element={<AdvisorPanel />} />
        <Route path="/composer" element={<ComposerPanel />} />
        <Route path="/effects" element={<EffectsExplorer />} />
        <Route path="/generator" element={<GeneratorPanel />} />
        <Route path="/guide/po33" element={<PO33Guide />} />
        <Route path="/guide/ep133" element={<EP133Guide />} />
        <Route path="*" element={<Navigate to="/advisor" replace />} />
      </Routes>
    </AppShell>
  );
}
