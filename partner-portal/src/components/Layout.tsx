import { NavLink, Outlet } from "react-router-dom";
import { ApiError, compositeUrl } from "../api/client";
import { useMe } from "../api/hooks";
import { isDevMode, logout } from "../auth";
import NotPartnerPage from "../pages/NotPartnerPage";
import "./Layout.css";

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

export default function Layout() {
  const me = useMe();

  // 403 on /me: signed in, but no partner_id claim or no partner role.
  if (me.error instanceof ApiError && me.error.status === 403) return <NotPartnerPage />;

  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-left">
          <img src="/openg2p-logo.svg" alt="OpenG2P" className="logo" />
          <span className="product">Partner Portal</span>
        </div>
        <nav className="topnav">
          <NavLink to="/requests" className={navClass}>
            Requests
          </NavLink>
          <NavLink to="/consents" className={navClass}>
            Consents
          </NavLink>
          <NavLink to="/access" className={navClass}>
            What we can ask for
          </NavLink>
          {compositeUrl() && (
            <NavLink to="/use-cases" className={navClass}>
              Use cases
            </NavLink>
          )}
        </nav>
        <div className="topbar-right">
          {isDevMode() && <span className="dev-pill">dev</span>}
          {me.data && (
            <span className="user" title={me.data.roles.join(", ")}>
              {me.data.name || me.data.username}
              <span className="user-partner">{me.data.partner_id}</span>
            </span>
          )}
          <button className="btn-secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        {me.isLoading && <div className="loading">Loading your account…</div>}
        {me.error && !(me.error instanceof ApiError && me.error.status === 401) && (
          <div className="notice notice-error">
            Could not load your account. {me.error instanceof Error ? me.error.message : ""}
          </div>
        )}
        {me.data && <Outlet />}
      </main>
      <footer className="footer">
        OpenG2P Consent Manager · partner portal · consent you can prove
      </footer>
    </div>
  );
}
