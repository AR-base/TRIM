import { useState } from "react";

import { useSession } from "../App";
import { ApiError } from "../api";
import { Empty, ErrorNote } from "../components/Bits";
import { useToast } from "../components/Toast";
import { relativeTime } from "../format";
import { href } from "../router";
import type { RequestView } from "../types";
import { useLoad } from "../useLoad";

const DURATIONS = [
  { minutes: 15, label: "15 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 240, label: "4 hours" },
  { minutes: 1440, label: "1 day" },
];

const STATUS_LABEL: Record<RequestView["status"], string> = {
  pending: "Waiting",
  approved_once: "Allowed once",
  approved_always: "Allowed always",
  denied: "Denied",
  expired: "Ended",
};

export function RequestsPage() {
  const { api, me, refreshSummary, summary } = useSession();
  const toast = useToast();
  const requests = useLoad(() => api.requests(), [api]);
  const pending = (requests.data ?? []).filter((r) => r.status === "pending");
  const decided = (requests.data ?? []).filter((r) => r.status !== "pending");

  async function decide(r: RequestView, choice: "allow_once" | "allow_always" | "deny", minutes?: number) {
    try {
      await api.decide(r.id, choice, minutes);
      toast({
        tone: "ok",
        text: choice === "deny" ? `Denied ${r.agent_name}.` : choice === "allow_once" ? `Allowed ${r.agent_name} for a limited time.` : `Allowed ${r.agent_name}.`,
      });
      await Promise.all([requests.refresh(), refreshSummary()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "That didn't work." });
    }
  }

  return (
    <div className="page">
      <header className="pagehead">
        <p className="eyebrow">Requests</p>
        <h1>Agents asking for more</h1>
        <p className="muted">Like a phone asking for your location: allow once, allow always, or deny.</p>
      </header>
      {summary && !summary.can_restore && (
        <p className="note">Your provider asks the user to grant new permissions, so decisions here are recorded for audit only.</p>
      )}
      {requests.error && <ErrorNote message={requests.error.message} onRetry={requests.refresh} />}
      <div className="cards">
        {pending.map((r) => (
          <RequestCard key={r.id} r={r} canDecide={me.can_change_access} onDecide={decide} />
        ))}
      </div>
      {requests.data && pending.length === 0 && <Empty title="No one is waiting.">New requests appear here as agents make them.</Empty>}

      {decided.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Decided</h2>
          {decided.map((r) => (
            <div key={r.id} className="decision">
              <span className={`decision__action decision__action--${r.status}`}>{STATUS_LABEL[r.status]}</span>
              <span className="decision__what">
                <b>{r.agent_name}</b> · {r.phrases.join(", ")} · {r.user_email} · {r.decided_by ?? "system"}{" "}
                {r.expires_at && r.status === "approved_once" ? `· ends ${relativeTime(r.expires_at)}` : ""}
              </span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function RequestCard({
  r,
  canDecide,
  onDecide,
}: {
  r: RequestView;
  canDecide: boolean;
  onDecide: (r: RequestView, c: "allow_once" | "allow_always" | "deny", minutes?: number) => void;
}) {
  const [minutes, setMinutes] = useState(60);
  return (
    <article className="card card--request">
      <p className="ask-sentence">
        <a href={href({ name: "agent", id: r.agent_id })}>{r.agent_name}</a> wants to <b>{r.phrases.join(" and ")}</b> for{" "}
        {r.user_email}.
      </p>
      {r.justification && <p className="quote">“{r.justification}”</p>}
      <p className="muted small">
        {r.scopes.map((s) => (
          <code key={s} className="tag">
            {s.replace("https://www.googleapis.com/auth/", "")}
          </code>
        ))}{" "}
        · asked {relativeTime(r.created_at)}
      </p>
      {canDecide && (
        <footer className="card__actions card__actions--stack">
          <span className="once">
            <button className="btn btn--ink btn--sm" onClick={() => onDecide(r, "allow_once", minutes)}>
              Allow once
            </button>
            <select aria-label="For how long" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
              {DURATIONS.map((d) => (
                <option key={d.minutes} value={d.minutes}>
                  for {d.label}
                </option>
              ))}
            </select>
          </span>
          <button className="btn btn--ghost btn--sm" onClick={() => onDecide(r, "allow_always")}>
            Allow always
          </button>
          <button className="btn btn--ghost btn--sm btn--deny" onClick={() => onDecide(r, "deny")}>
            Deny
          </button>
        </footer>
      )}
    </article>
  );
}
