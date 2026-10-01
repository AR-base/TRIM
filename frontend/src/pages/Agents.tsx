import { useEffect, useState } from "react";

import { useSession } from "../App";
import { Empty, ErrorNote, RiskDots, StateBadge } from "../components/Bits";
import { CountStrip } from "../components/Strip";
import { plural, relativeTime, STATE_LABEL } from "../format";
import { href } from "../router";
import type { AgentState } from "../types";
import { useLoad } from "../useLoad";

const FILTERS: (AgentState | "")[] = ["", "ready", "learning", "trimmed", "right_sized", "suspended", "exempt"];

export function AgentsPage() {
  const { api } = useSession();
  const [state, setState] = useState<AgentState | "">("");
  const [can, setCan] = useState("");
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const h = window.setTimeout(() => setQ(query.trim().slice(0, 100)), 250);
    return () => window.clearTimeout(h);
  }, [query]);
  const caps = useLoad(() => api.capabilities(), [api]);
  const agents = useLoad(() => api.agents({ state, q, can }), [api, state, q, can]);
  const capLabel = caps.data?.find((c) => c.key === can)?.label;

  return (
    <div className="page">
      <header className="pagehead">
        <p className="eyebrow">Agents</p>
        <h1>Every AI agent with access to company data</h1>
      </header>

      <div className="ask" role="search">
        <label htmlFor="can" className="ask__label">
          Which agents can
        </label>
        <select id="can" value={can} onChange={(e) => setCan(e.target.value)} className="ask__select">
          <option value="">do anything</option>
          {(caps.data ?? []).map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
        <span className="ask__q">?</span>
        <input
          className="ask__search"
          type="search"
          placeholder="Filter by name"
          value={query}
          maxLength={100}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Filter agents by name"
        />
      </div>

      <div className="chips" role="group" aria-label="Filter by state">
        {FILTERS.map((f) => (
          <button key={f || "all"} className={`chip${state === f ? " chip--on" : ""}`} onClick={() => setState(f)} aria-pressed={state === f}>
            {f ? STATE_LABEL[f] : "All"}
          </button>
        ))}
      </div>

      {agents.error && <ErrorNote message={agents.error.message} onRetry={agents.refresh} />}
      {agents.data && (
        <p className="resultline" aria-live="polite">
          {plural(agents.data.length, "agent")}
          {capLabel ? ` can ${capLabel}` : ""}.
        </p>
      )}

      <div className={`table${agents.loading ? " table--loading" : ""}`} role="table" aria-label="Agents">
        <div className="table__head" role="row">
          <span role="columnheader">Agent</span>
          <span role="columnheader">What it can do today</span>
          <span role="columnheader">Permissions</span>
          <span role="columnheader">State</span>
        </div>
        {(agents.data ?? []).map((a) => (
          <a key={a.id} className="table__row" role="row" href={href({ name: "agent", id: a.id })}>
            <span role="cell" className="agentcell">
              <b>{a.name}</b>
              <span className="muted small">
                {plural(a.users, "person", "people")} · active {relativeTime(a.last_activity)}
              </span>
            </span>
            <span role="cell" className="reachcell">
              {a.reach}
            </span>
            <span role="cell" className="permcell">
              <CountStrip granted={a.granted} unused={a.unused} />
              <span className="small muted">
                {a.unused > 0 ? `${a.unused} of ${a.granted} unused` : `${a.granted} in use`} · <RiskDots risk={a.risk} />
              </span>
            </span>
            <span role="cell" className="statecell">
              <StateBadge state={a.state} />
              {a.open_alerts > 0 && <span className="alertpill">{plural(a.open_alerts, "alert")}</span>}
            </span>
          </a>
        ))}
        {agents.data?.length === 0 && <Empty title="No agents match.">Try another question or clear the filters.</Empty>}
      </div>
    </div>
  );
}
