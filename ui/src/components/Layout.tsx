import { NavLink, Outlet } from "react-router-dom";
import { currentUser, isAdmin, isApprover, isDevMode, logout } from "../auth";
import "./Layout.css";

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

export default function Layout() {
  const admin = isAdmin();
  const approver = isApprover();
  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-left">
          <img src="/openg2p-logo.svg" alt="OpenG2P" className="logo" />
          <span className="product">Consent Manager</span>
        </div>
        <nav className="topnav">
          {admin && (
            <NavLink to="/partners" className={navClass}>
              Partner policies
            </NavLink>
          )}
          {approver && (
            <NavLink to="/approvals" className={navClass}>
              Approvals
            </NavLink>
          )}
          {admin && (
            <NavLink to="/decisions" className={navClass}>
              Decisions
            </NavLink>
          )}
          <NavLink to="/my/consents" className={navClass}>
            My Consents
          </NavLink>
        </nav>
        <div className="topbar-right">
          {isDevMode() && <span className="dev-pill">dev</span>}
          <span className="user">{currentUser()}</span>
          <button className="btn-secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <footer className="footer">
        OpenG2P Consent Manager · governs verifiable, policy-bound data sharing
      </footer>
    </div>
  );
}
