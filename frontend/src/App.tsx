import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, ApiError, tokenStore, type Api } from "./api";
import { Mark } from "./components/Bits";
import { ToastProvider } from "./components/Toast";
import { relativeTime } from "./format";
import { AgentDetailPage } from "./pages/AgentDetail";
import { AgentsPage } from "./pages/Agents";
import { AlertsPage } from "./pages/Alerts";
import { HistoryPage } from "./pages/History";
import { OverviewPage } from "./pages/Overview";
import { RequestsPage } from "./pages/Requests";
import { SignIn } from "./pages/SignIn";
import { href, useRoute, type Route } from "./router";
import type { Me, Summary } from "./types";

interface Session {
  api: Api;
  me: Me;
  summary: Summary | null;
  refreshSummary: () => Promise<void>;
}

const SessionCtx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(SessionCtx);
  if (!s) throw new Error("useSession outside of a signed-in session");
  return s;
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(() => Boolean(tokenStore.get()));
  const [summary, setSummary] = useState<Summary | null>(null);

  const signOut = useCallback(() => {
    tokenStore.clear();
    setMe(null);
    setSummary(null);
  }, []);

  const refreshSummary = useCallback(async () => {
    try {
      setSummary(await api.summary());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) signOut();
    }
  }, [signOut]);

  useEffect(() => {
    if (!tokenStore.get()) return;
    api
      .me()
      .then(setMe)
      .catch(() => tokenStore.clear())
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    if (me) void refreshSummary();
  }, [me, refreshSummary]);

  if (checking) return <div className="boot" aria-busy="true" />;
  if (!me) return <SignIn onSignedIn={setMe} />;

  return (
    <ToastProvider>
      <SessionCtx.Provider value={{ api, me, summary, refreshSummary }}>
        <Shell me={me} summary={summary} onSignOut={signOut} />
      </SessionCtx.Provider>
    </ToastProvider>
  );
}

const NAV: { route: Route; label: string; count?: (s: Summary) => number }[] = [
  { route: { name: "overview" }, label: "Overview" },
  { route: { name: "agents" }, label: "Agents", count: (s) => s.agents },
  { route: { name: "alerts" }, label: "Alerts", count: (s) => s.open_alerts },
  { route: { name: "requests" }, label: "Requests", count: (s) => s.pending_requests },
  { route: { name: "history" }, label: "History" },
];

function Shell({ me, summary, onSignOut }: { me: Me; summary: Summary | null; onSignOut: () => void }) {
  const route = useRoute();
  const active = route.name === "agent" ? "agents" : route.name;
  return (
    <div className="shell">
      <aside className="side">
        <a className="brand" href="#/">
          <Mark />
          <span>trim</span>
        </a>
        <nav aria-label="Main">
          {NAV.map((n) => {
            const c = summary && n.count ? n.count(summary) : 0;
            const urgent = n.route.name === "alerts" || n.route.name === "requests";
            return (
              <a
                key={n.label}
                href={href(n.route)}
                className={`nav${active === n.route.name ? " nav--active" : ""}`}
                aria-current={active === n.route.name ? "page" : undefined}
              >
                <span>{n.label}</span>
                {c > 0 && <span className={`nav__count${urgent ? " nav__count--urgent" : ""}`}>{c}</span>}
              </a>
            );
          })}
        </nav>
        <div className="side__foot">
          {summary && (
            <p className="side__meta">
              <span className="dot dot--live" /> {summary.provider === "simulated" ? "Test organisation" : "Google Workspace"}
              <br />
              Synced {relativeTime(summary.last_sync)}
            </p>
          )}
          <p className="side__who">
            {me.name} · <span className="mono">{me.role}</span>
          </p>
          <button className="linkish" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="main" id="main">
        <Page route={route} />
      </main>
    </div>
  );
}

function Page({ route }: { route: Route }) {
  switch (route.name) {
    case "overview":
      return <OverviewPage />;
    case "agents":
      return <AgentsPage />;
    case "agent":
      return <AgentDetailPage id={route.id} />;
    case "alerts":
      return <AlertsPage />;
    case "requests":
      return <RequestsPage />;
    case "history":
      return <HistoryPage />;
  }
}
