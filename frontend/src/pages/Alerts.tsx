import { useState } from "react";

import { useSession } from "../App";
import { ApiError } from "../api";
import { Empty, ErrorNote } from "../components/Bits";
import { useToast } from "../components/Toast";
import { shortDate } from "../format";
import { href } from "../router";
import type { AlertView } from "../types";
import { useLoad } from "../useLoad";

const TABS = [
  { key: "open", label: "Open" },
  { key: "confirmed", label: "Confirmed" },
  { key: "dismissed", label: "Dismissed" },
] as const;

export function AlertsPage() {
  const { api, me, refreshSummary } = useSession();
  const toast = useToast();
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("open");
  const alerts = useLoad(() => api.alerts(tab), [api, tab]);

  async function run(fn: () => Promise<unknown>, text: string) {
    try {
      await fn();
      toast({ tone: "ok", text });
      await Promise.all([alerts.refresh(), refreshSummary()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "That didn't work." });
    }
  }

  return (
    <div className="page">
      <header className="pagehead">
        <p className="eyebrow">Alerts</p>
        <h1>Agents behaving unlike themselves</h1>
        <p className="muted">
          Each agent is compared with its own first two weeks. An alert needs a high anomaly score and a concrete reason.
        </p>
      </header>
      <div className="chips" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={`chip${tab === t.key ? " chip--on" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {alerts.error && <ErrorNote message={alerts.error.message} onRetry={alerts.refresh} />}
      <div className="cards">
        {(alerts.data ?? []).map((a) => (
          <AlertCard
            key={a.id}
            a={a}
            canSuspend={me.can_change_access}
            onReview={(status) => run(() => api.reviewAlert(a.id, status), status === "confirmed" ? "Marked as suspicious." : "Dismissed as benign.")}
            onSuspend={() => run(() => api.suspend(a.agent_id, `alert #${a.id}`), `${a.agent_name} suspended.`)}
          />
        ))}
      </div>
      {alerts.data?.length === 0 && <Empty title={tab === "open" ? "No open alerts." : `No ${tab} alerts.`} />}
    </div>
  );
}

function AlertCard({
  a,
  canSuspend,
  onReview,
  onSuspend,
}: {
  a: AlertView;
  canSuspend: boolean;
  onReview: (s: "confirmed" | "dismissed") => void;
  onSuspend: () => void;
}) {
  return (
    <article className="card card--alert">
      <header className="card__head">
        <a href={href({ name: "agent", id: a.agent_id })} className="card__title">
          {a.agent_name}
        </a>
        <span className="muted">{shortDate(a.day)}</span>
        <span className="score" title="Anomaly score">
          {a.score.toFixed(2)}
        </span>
      </header>
      <ul className="reasons">
        {a.reasons.map((r) => (
          <li key={r.feature}>
            <span className="reasons__z num">{r.z.toFixed(1)}σ</span>
            {r.text}
          </li>
        ))}
      </ul>
      {a.status === "open" && (
        <footer className="card__actions">
          <button className="btn btn--ghost btn--sm" onClick={() => onReview("dismissed")}>
            Benign
          </button>
          <button className="btn btn--ink btn--sm" onClick={() => onReview("confirmed")}>
            Suspicious
          </button>
          {canSuspend && (
            <button className="btn btn--danger btn--sm" onClick={onSuspend}>
              Suspend agent
            </button>
          )}
        </footer>
      )}
    </article>
  );
}
