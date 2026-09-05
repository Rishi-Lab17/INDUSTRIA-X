import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import SovereigntyBadge from "./SovereigntyBadge";

const LINKS = [
  { to: "/", label: "Dashboard" },
  { to: "/workspace", label: "Company Workspace" },
  { to: "/equipment", label: "Equipment" },
  { to: "/knowledge", label: "Knowledge Base" },
  { to: "/search", label: "Knowledge Search" },
  { to: "/workbench", label: "AI Workbench" },
  { to: "/investigations", label: "Investigations" },
  { to: "/evidence", label: "Evidence Center" },
  { to: "/audit", label: "Audit Trail" },
  { to: "/sovereignty", label: "Sovereignty Center" },
  { to: "/health", label: "System Health" },
];

export default function Layout() {
  const { user, company, logout } = useAuth();
  const nav = useNavigate();

  async function onLogout() {
    await logout();
    nav("/login");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">IX</div>
          <div>
            <div className="brand-name">INDUSTRIA-X</div>
            <div className="brand-sub">SOVEREIGN AI WORKBENCH</div>
          </div>
        </div>
        {LINKS.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.to === "/"} className={({ isActive }) =>
            isActive ? "nav-link active" : "nav-link"}>
            {l.label}
          </NavLink>
        ))}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
          <SovereigntyBadge />
          <div className="panel" style={{ padding: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{user?.name}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>{user?.role} · {company}</div>
            <button className="btn btn-ghost" style={{ marginTop: 10, width: "100%" }} onClick={onLogout}>
              Logout
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <Outlet />
      </div>
    </div>
  );
}
