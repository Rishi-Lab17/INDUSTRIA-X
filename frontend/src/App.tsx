import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Register from "./pages/Register";
import PhoneVerify from "./pages/PhoneVerify";
import Workspace from "./pages/Workspace";
import EquipmentList from "./pages/EquipmentList";
import EquipmentForm from "./pages/EquipmentForm";
import EquipmentDetail from "./pages/EquipmentDetail";
import KnowledgeBase from "./pages/KnowledgeBase";
import DocumentDetail from "./pages/DocumentDetail";
import Search from "./pages/Search";
import Eval from "./pages/Eval";
import Workbench from "./pages/Workbench";
import SensorIntel from "./pages/SensorIntel";
import VisionIntel from "./pages/VisionIntel";
import Multimodal from "./pages/Multimodal";
import Investigations from "./pages/Investigations";
import InvestigationDetail from "./pages/InvestigationDetail";
import Verifications from "./pages/Verifications";
import VerificationDetail from "./pages/VerificationDetail";
import SafetyCenter from "./pages/SafetyCenter";
import ApprovalInbox from "./pages/ApprovalInbox";
import Cases from "./pages/Cases";
import CaseDetail from "./pages/CaseDetail";
import MemoryPage from "./pages/MemoryPage";
import ReportsPage from "./pages/ReportsPage";
import LineagePage from "./pages/LineagePage";
import ReplayPage from "./pages/ReplayPage";
import CaseAuditPage from "./pages/CaseAuditPage";
import SovereigntyPage from "./pages/SovereigntyPage";
import SystemHealth from "./pages/SystemHealth";
import EvidenceCenter from "./pages/EvidenceCenter";
import LiveInvestigation from "./pages/LiveInvestigation";
import type { JSX } from "react";

function Guard({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="auth-wrap"><div style={{ color: "var(--muted)" }}>Loading session...</div></div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<Guard><Layout /></Guard>}>
            <Route index element={<Dashboard />} />
            <Route path="verify-phone" element={<PhoneVerify />} />
            <Route path="workspace" element={<Workspace />} />
            <Route path="equipment" element={<EquipmentList />} />
            <Route path="equipment/new" element={<EquipmentForm />} />
            <Route path="equipment/:id" element={<EquipmentDetail />} />
            <Route path="equipment/:id/edit" element={<EquipmentForm />} />
            <Route path="knowledge" element={<KnowledgeBase />} />
            <Route path="knowledge/:id" element={<DocumentDetail />} />
            <Route path="search" element={<Search />} />
            <Route path="eval" element={<Eval />} />
            <Route path="workbench" element={<Workbench />} />
            <Route path="sensors" element={<SensorIntel />} />
            <Route path="vision" element={<VisionIntel />} />
            <Route path="multimodal" element={<Multimodal />} />
            <Route path="investigations" element={<Investigations />} />
            <Route path="investigations/:id" element={<InvestigationDetail />} />
            <Route path="verifications" element={<Verifications />} />
            <Route path="verifications/:id" element={<VerificationDetail />} />
            <Route path="safety-center" element={<SafetyCenter />} />
            <Route path="approvals" element={<ApprovalInbox />} />
            <Route path="evidence" element={<EvidenceCenter />} />
            <Route path="audit" element={<CaseAuditPage />} />
            <Route path="cases" element={<Cases />} />
            <Route path="cases/:id" element={<CaseDetail />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="lineage" element={<LineagePage />} />
            <Route path="replay" element={<ReplayPage />} />
            <Route path="case-audit" element={<CaseAuditPage />} />
            <Route path="sovereignty" element={<SovereigntyPage />} />
            <Route path="health" element={<SystemHealth />} />
            <Route path="live-investigation" element={<LiveInvestigation />} />
            <Route path="investigations/:id/live" element={<LiveInvestigation />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
