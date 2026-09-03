import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Verify from "./pages/Verify";
import PhoneVerify from "./pages/PhoneVerify";
import Stub from "./pages/Stub";
import type { JSX } from "react";

function Guard({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="auth-wrap"><div style={{ color: "var(--muted)" }}>Loading session…</div></div>;
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
          <Route path="/verify" element={<Verify />} />
          <Route path="/" element={<Guard><Layout /></Guard>}>
            <Route index element={<Dashboard />} />
            <Route path="verify-phone" element={<PhoneVerify />} />
            <Route path="workspace" element={<Stub title="Company Workspace" stage="Stage 2" desc="Tenant members, roles and equipment fleet overview." />} />
            <Route path="equipment" element={<Stub title="Equipment" stage="Stage 2" desc="Equipment Digital Passport with QR identity." />} />
            <Route path="knowledge" element={<Stub title="Knowledge Base" stage="Stage 3" desc="Secure document upload, OCR and processing pipeline." />} />
            <Route path="investigations" element={<Stub title="Investigations" stage="Stage 5–8" desc="Agentic workbench, hypotheses, verification and approval." />} />
            <Route path="evidence" element={<Stub title="Evidence Center" stage="Stage 7" desc="Structured evidence cards and evidence graph." />} />
            <Route path="audit" element={<Stub title="Audit Trail" stage="Stage 9" desc="Searchable audit log of every important action." />} />
            <Route path="sovereignty" element={<Stub title="Sovereignty Center" stage="Stage 9" desc="Live local-processing guarantees and service status." />} />
            <Route path="health" element={<Stub title="System Health" stage="Stage 9" desc="Live health of backend, DB, vector DB, Kimi, RAG and engines." />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
