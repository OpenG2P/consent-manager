import { NavLink, Outlet } from "react-router-dom";
import { currentUser, isAdmin, isDevMode, logout } from "../auth";
import "./Layout.css";

export default function Layout() {
  const admin = isAdmin();
  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-left">
          <img src="/openg2p-logo.svg" alt="OpenG2P" className="logo" />
          <span className="product">Consent Manager</span>
        </div>
        <nav className="topnav">
          {admin && (
            <NavLink to="/partners" className={({ isActive }) => (isActive ? "active" : "")}>
              Partners
            </NavLink>
          )}
          <NavLink to="/my/consents" className={({ isActive }) => (isActive ? "active" : "")}>
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
