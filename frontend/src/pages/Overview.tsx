import { useState } from "react";

import { useSession } from "../App";
import { ApiError } from "../api";
import { Empty, ErrorNote, RiskDots, StateBadge } from "../components/Bits";
import { Confirm } from "../components/Confirm";
import { CountStrip } from "../components/Strip";
import { useToast } from "../components/Toast";
import { plural, relativeTime, shortDate, STATE_LABEL } from "../format";
import { href } from "../router";
import type { AgentState } from "../types";
import { useLoad } from "../useLoad";

const ORDER: AgentState[] = ["ready", "learning", "trimmed", "right_sized", "exempt", "suspended"];

export function OverviewPage() {
  const { api, me, summary, refreshSummary } = useSession();
  const toast = useToast();
  const agents = useLoad(() => api.agents(), [api]);
  const alerts = useLoad(() => api.alerts("open"), [api]);
  const requests = useLoad(() => api.requests("pending"), [api]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!summary) return <div className="page" aria-busy="true" />;
  const ready = summary.by_state.ready ?? 0;
  const pct = summary.granted_permissions ? Math.round((summary.unused_permissions / summary.granted_permissions) * 100) : 0;

  async function trimAll() {
    setBusy(true);
    try {
      const r = await api.trimAll(!summary!.can_narrow);
      setConfirming(false);
      toast({
        tone: r.skipped.length ? "error" : "ok",
        text: `Trimmed ${plural(r.trimmed.length, "agent")}${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}.`,
      });
      await Promise.all([refreshSummary(), agents.refresh()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "Trim failed." });
    } finally {
      setBusy(false);
    }
  }

  const cuts = (agents.data ?? []).filter((a) => a.state === "ready").sort((a, b) => b.unused * b.risk - a.unused * a.risk);

  return (
    <div className="page">
      <header className="hero">
        <p className="eyebrow">Overview · synced {relativeTime(summary.last_sync)}</p>
        <h1 className="hero__title">
          <span className="num">{summary.agents}</span> AI agents hold <span className="num">{summary.granted_permissions}</span>{" "}
          permissions.{" "}
          <span className="hero__cut">
            <span className="num">{summary.unused_permissions}</span> were never used.
          </span>
        </h1>
        <div className="hero__actions">
          {me.can_change_access && ready > 0 && (
            <button className="btn btn--cut btn--lg" onClick={() => setConfirming(true)}>
              Trim all {plural(ready, "agent")}
            </button>
          )}
          <a className="btn btn--ghost btn--lg" href={href({ name: "agents" })}>
            See every agent
          </a>
        </div>
      </header>

      <section className="stats" aria-label="Key numbers">
        <Stat value={`${pct}%`} label="of granted access is unused" tone={pct > 0 ? "cut" : undefined} />
        <Stat value={summary.high_risk_agents} label="agents can delete data, change accounts or share files" />
        <Stat value={summary.users} label="people have connected agents" />
        <Stat value={summary.active_grants} label="active grants across the organisation" />
      </section>

      <section className="panel">
        <h2 className="panel__title">Where every agent stands</h2>
        <div className="statebar" role="img" aria-label={ORDER.map((s) => `${summary.by_state[s] ?? 0} ${STATE_LABEL[s]}`).join(", ")}>
          {ORDER.map((s) =>
            (summary.by_state[s] ?? 0) > 0 ? (
              <span key={s} className={`statebar__seg statebar__seg--${s}`} style={{ flexGrow: summary.by_state[s] }} />
            ) : null,
          )}
        </div>
        <ul className="legend">
          {ORDER.map((s) => (
            <li key={s}>
              <i className={`legend__sw statebar__seg--${s}`} /> {STATE_LABEL[s]} <b className="num">{summary.by_state[s] ?? 0}</b>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid2">
        <section className="panel">
          <h2 className="panel__title">
            Needs your decision{" "}
            <span className="muted">
              {summary.open_alerts + summary.pending_requests > 0 ? `· ${summary.open_alerts + summary.pending_requests}` : ""}
            </span>
          </h2>
          {alerts.error && <ErrorNote message={alerts.error.message} onRetry={alerts.refresh} />}
          {(alerts.data ?? []).slice(0, 4).map((a) => (
            <a key={`a${a.id}`} className="inbox" href={href({ name: "agent", id: a.agent_id })}>
              <span className="inbox__kind inbox__kind--alert">Alert</span>
              <span className="inbox__main">
                <span>
                  <b>{a.agent_name}</b> · {shortDate(a.day)}
                </span>
                <span className="inbox__sub">{a.reasons[0]?.text}</span>
              </span>
            </a>
          ))}
          {(requests.data ?? []).slice(0, 4).map((r) => (
            <a key={`r${r.id}`} className="inbox" href={href({ name: "requests" })}>
              <span className="inbox__kind">Request</span>
              <span className="inbox__main">
                <span>
                  <b>{r.agent_name}</b> wants to {r.phrases.join(" and ")}
                </span>
                <span className="inbox__sub">for {r.user_email}</span>
              </span>
            </a>
          ))}
          {alerts.data?.length === 0 && requests.data?.length === 0 && (
            <Empty title="Nothing waiting.">No open alerts and no pending permission requests.</Empty>
          )}
        </section>

        <section className="panel">
          <h2 className="panel__title">Biggest cuts</h2>
          {agents.error && <ErrorNote message={agents.error.message} onRetry={agents.refresh} />}
          {cuts.slice(0, 6).map((a) => (
            <a key={a.id} className="cutrow" href={href({ name: "agent", id: a.id })}>
              <span className="cutrow__name">
                {a.name} <RiskDots risk={a.risk} />
              </span>
              <CountStrip granted={a.granted} unused={a.unused} />
              <span className="cutrow__n num">−{a.unused}</span>
            </a>
          ))}
          {agents.data && cuts.length === 0 && (
            <Empty title="Everything is right-sized.">No agent holds a permission it hasn't used.</Empty>
          )}
          {agents.data && cuts.length > 0 && (
            <p className="panel__foot">
              <StateBadge state="ready" /> agents are past their {plural(14, "day")} learning period.
            </p>
          )}
        </section>
      </div>

      {confirming && (
        <Confirm
          title={`Trim ${plural(ready, "agent")}?`}
          confirmLabel={`Remove ${plural(summary.unused_permissions, "permission")}`}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={trimAll}
        >
          {summary.can_narrow ? (
            <p>
              Each agent keeps only the permissions it used in the last 14 days. Every change is recorded and can be undone in
              one click from History.
            </p>
          ) : (
            <p>
              Your provider can't narrow permissions in place, so agents with unused permissions will lose access and their
              owners will be asked to reconnect with fewer permissions. This can't be undone automatically.
            </p>
          )}
        </Confirm>
      )}
    </div>
  );
}

function Stat({ value, label, tone }: { value: number | string; label: string; tone?: "cut" }) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ""}`}>
      <span className="stat__value num">{value}</span>
      <span className="stat__label">{label}</span>
    </div>
  );
}
