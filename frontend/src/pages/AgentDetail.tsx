import { useState } from "react";

import { useSession } from "../App";
import { ApiError } from "../api";
import { ActivityBars } from "../components/ActivityBars";
import { Empty, ErrorNote, RiskDots, StateBadge } from "../components/Bits";
import { Confirm } from "../components/Confirm";
import { PermissionStrip } from "../components/Strip";
import { useToast } from "../components/Toast";
import { ACTION_LABEL, plural, relativeTime, riskLabel, shortDate } from "../format";
import { href } from "../router";
import type { AgentDetail, ScopeView } from "../types";
import { useLoad } from "../useLoad";

type Dialog = "trim" | "suspend" | null;

export function AgentDetailPage({ id }: { id: number }) {
  const { api, me, refreshSummary } = useSession();
  const toast = useToast();
  const agent = useLoad(() => api.agent(id), [api, id]);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>, done: string, undoId?: (r: unknown) => number | undefined) {
    setBusy(true);
    try {
      const r = await fn();
      setDialog(null);
      const decisionId = undoId?.(r);
      toast({
        tone: "ok",
        text: done,
        action:
          decisionId !== undefined && agent.data?.can_restore
            ? { label: "Undo", run: () => void act(() => api.undo(decisionId), "Restored the previous access.") }
            : undefined,
      });
      await Promise.all([agent.refresh(), refreshSummary()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "That didn't work." });
    } finally {
      setBusy(false);
    }
  }

  if (agent.error && !agent.data) {
    return (
      <div className="page">
        <a className="back" href={href({ name: "agents" })}>
          ← Agents
        </a>
        <ErrorNote message={agent.error.status === 404 ? "This agent doesn't exist." : agent.error.message} onRetry={agent.refresh} />
      </div>
    );
  }
  const a = agent.data;
  if (!a) return <div className="page" aria-busy="true" />;

  const removable = a.scopes.filter((s) => s.status !== "used" && s.status !== "learning");
  const flagged = a.alerts.filter((x) => x.status !== "dismissed").map((x) => x.day);

  return (
    <div className="page">
      <a className="back" href={href({ name: "agents" })}>
        ← Agents
      </a>
      <header className="agenthead">
        <div>
          <p className="eyebrow mono">{a.client_id}</p>
          <h1>
            {a.name} <StateBadge state={a.state} />
          </h1>
          <p className="muted">
            Owner {a.owner_email || "unknown"} · first seen {shortDate(a.first_seen)} · last active {relativeTime(a.last_activity)}
          </p>
        </div>
        {me.can_change_access && (
          <div className="agenthead__actions">
            {a.state === "ready" && (
              <button className="btn btn--cut btn--lg" onClick={() => setDialog("trim")}>
                Trim {plural(removable.length, "permission")}
              </button>
            )}
            {a.state !== "suspended" && a.grants.length > 0 && (
              <button className="btn btn--ghost" onClick={() => setDialog("suspend")}>
                Suspend
              </button>
            )}
            {(a.state === "ready" || a.state === "exempt" || a.state === "right_sized") && (
              <button
                className="btn btn--ghost"
                onClick={() =>
                  act(() => api.exempt(a.id, a.state !== "exempt"), a.state === "exempt" ? "Recommendations turned back on." : "Agent exempted.")
                }
              >
                {a.state === "exempt" ? "Remove exemption" : "Exempt"}
              </button>
            )}
          </div>
        )}
      </header>

      <section className={`beforeafter${a.state === "ready" || a.state === "learning" ? "" : " beforeafter--single"}`} aria-label="Reach">
        <div className="ba">
          <p className="ba__label">{a.state === "trimmed" ? "Today, after trim" : "Today"}</p>
          <p className="ba__text">{a.reach}</p>
        </div>
        {a.state === "ready" && (
          <div className="ba ba--after">
            <p className="ba__label">After trim</p>
            <p className="ba__text">{a.reach_after}</p>
          </div>
        )}
        {a.state === "learning" && (
          <div className="ba ba--same">
            <p className="ba__label">Learning</p>
            <p className="ba__text">
              Watching what it uses until {shortDate(a.learning_until!)}. Nothing will be recommended before then.
            </p>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel__row">
          <h2 className="panel__title">Permissions</h2>
          <Legend />
        </div>
        <PermissionStrip scopes={a.scopes} />
        <ul className="scopes">
          {a.scopes.map((s) => (
            <ScopeRow key={s.scope} s={s} detail={a} />
          ))}
        </ul>
        {a.dormant && <p className="note">This agent made no API calls in the last 14 days, so none of its access is justified.</p>}
      </section>

      <div className="grid2">
        <section className="panel">
          <h2 className="panel__title">
            Activity <span className="muted">· {plural(a.calls, "call")} in the window</span>
          </h2>
          <ActivityBars days={a.activity} flagged={flagged} excluded={a.excluded_days} windowStart={a.window_start} />
          {a.excluded_days.length > 0 && (
            <p className="small muted">
              {plural(a.excluded_days.length, "day")} with open alerts {a.excluded_days.length === 1 ? "is" : "are"} left out:
              suspicious activity never justifies keeping a permission.
            </p>
          )}
        </section>
        <section className="panel">
          <h2 className="panel__title">Alerts</h2>
          {a.alerts.length === 0 && <Empty title="No unusual behaviour." />}
          {a.alerts.slice(0, 4).map((al) => (
            <div key={al.id} className={`alertmini alertmini--${al.status}`}>
              <span className="alertmini__day">{shortDate(al.day)}</span>
              <span>{al.reasons[0]?.text}</span>
              <span className="muted small">{al.status}</span>
            </div>
          ))}
          {a.alerts.length > 0 && (
            <a className="linkish" href={href({ name: "alerts" })}>
              Review alerts →
            </a>
          )}
        </section>
      </div>

      <section className="panel">
        <h2 className="panel__title">Per person</h2>
        <div className="people">
          {a.grants.map((g) => (
            <div key={g.user_email} className="person">
              <span className="person__email">{g.user_email}</span>
              <span className="person__calls num">{g.calls}</span>
              <span className="person__scopes">
                {g.granted.map((s) => (
                  <code key={s} className={g.remove.includes(s) ? "tag tag--cut" : "tag"}>
                    {s}
                  </code>
                ))}
                {g.keep
                  .filter((k) => !g.granted.includes(k))
                  .map((k) => (
                    <code key={k} className="tag tag--new" title="Narrower permission Trim would grant instead">
                      + {k}
                    </code>
                  ))}
              </span>
            </div>
          ))}
          {a.grants.length === 0 && <Empty title="No one has granted this agent access." />}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel__title">Decisions</h2>
        {a.decisions.length === 0 && <Empty title="No changes yet." />}
        {a.decisions.map((d) => (
          <div key={d.id} className="decision">
            <span className={`decision__action decision__action--${d.action}`}>{ACTION_LABEL[d.action] ?? d.action}</span>
            <span className="decision__what">
              {d.removed > 0 && `−${d.removed}`} {d.added > 0 && `+${d.added}`} · {d.actor} · {relativeTime(d.created_at)}
              {d.undone_at && <span className="muted"> · undone</span>}
            </span>
            {me.can_change_access && d.undoable && (
              <button className="btn btn--ghost btn--sm" onClick={() => act(() => api.undo(d.id), "Restored the previous access.")}>
                Undo
              </button>
            )}
          </div>
        ))}
      </section>

      {dialog === "trim" && (
        <Confirm
          title={`Trim ${a.name}?`}
          confirmLabel={a.can_narrow ? "Trim" : "Revoke and ask owner to reconnect"}
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() =>
            act(
              () => api.trim(a.id, !a.can_narrow),
              `${a.name} trimmed.`,
              (r) => (r as { id: number }).id,
            )
          }
        >
          <p>It will keep only what it used in the last 14 days:</p>
          <p className="dialog__quote">{a.reach_after}</p>
          {!a.can_narrow && (
            <p className="note">This provider can't narrow access in place: Trim will revoke it and the owner reconnects with fewer permissions.</p>
          )}
        </Confirm>
      )}
      {dialog === "suspend" && (
        <Confirm
          title={`Suspend ${a.name}?`}
          tone="danger"
          confirmLabel="Remove all access"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => act(() => api.suspend(a.id, "suspended from the dashboard"), `${a.name} suspended.`, (r) => (r as { id: number }).id)}
        >
          <p>
            Every permission this agent holds for {plural(a.users, "person", "people")} is removed now. {a.can_restore ? "You can undo this." : ""}
          </p>
        </Confirm>
      )}
    </div>
  );
}

function ScopeRow({ s, detail }: { s: ScopeView; detail: AgentDetail }) {
  const methods = Array.from(new Set(detail.grants.flatMap((g) => g.reasons[s.short] ?? [])));
  return (
    <li className={`scope scope--${s.status}`}>
      <span className="scope__name">
        <code>{s.short}</code> <RiskDots risk={s.risk} />
      </span>
      <span className="scope__phrase">Can {s.phrase}</span>
      <span className="scope__why">
        {s.status === "used" && (methods.length ? <>Used: {methods.slice(0, 3).join(", ")}</> : "Needed to sign in")}
        {s.status === "narrowed" && <>Replace with {s.narrowed_to.map((n) => <code key={n}>{n}</code>)}</>}
        {s.status === "unused" && "Never used — remove"}
        {s.status === "learning" && "Watching"}
      </span>
      <span className="scope__risk muted small">{riskLabel(s.risk)} · {plural(s.users, "person", "people")}</span>
    </li>
  );
}

function Legend() {
  return (
    <ul className="legend legend--inline">
      <li>
        <i className="legend__sw strip__seg--used" /> In use
      </li>
      <li>
        <i className="legend__sw strip__seg--narrowed" /> Can be narrowed
      </li>
      <li>
        <i className="legend__sw strip__seg--unused" /> Never used
      </li>
    </ul>
  );
}
