import { useSession } from "../App";
import { ApiError } from "../api";
import { Empty, ErrorNote } from "../components/Bits";
import { useToast } from "../components/Toast";
import { ACTION_LABEL, plural, relativeTime } from "../format";
import { href } from "../router";
import { useLoad } from "../useLoad";

export function HistoryPage() {
  const { api, me, refreshSummary } = useSession();
  const toast = useToast();
  const decisions = useLoad(() => api.decisions(), [api]);

  async function undo(id: number) {
    try {
      await api.undo(id);
      toast({ tone: "ok", text: "Restored the previous access." });
      await Promise.all([decisions.refresh(), refreshSummary()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "Undo failed." });
    }
  }

  return (
    <div className="page">
      <header className="pagehead">
        <p className="eyebrow">History</p>
        <h1>Every change Trim made, and who approved it</h1>
      </header>
      {decisions.error && <ErrorNote message={decisions.error.message} onRetry={decisions.refresh} />}
      <ol className="timeline">
        {(decisions.data ?? []).map((d) => (
          <li key={d.id} className={`timeline__item${d.undone_at ? " timeline__item--undone" : ""}`}>
            <span className={`decision__action decision__action--${d.action}`}>{ACTION_LABEL[d.action] ?? d.action}</span>
            <div className="timeline__body">
              <p>
                <a href={href({ name: "agent", id: d.agent_id })}>
                  <b>{d.agent_name}</b>
                </a>{" "}
                {d.removed > 0 && <span className="cutnum">−{plural(d.removed, "permission")}</span>}{" "}
                {d.added > 0 && <span className="addnum">+{plural(d.added, "permission")}</span>}{" "}
                across {plural(Object.keys(d.before).length || Object.keys(d.after).length, "person", "people")}
              </p>
              <p className="muted small">
                {d.reason} · by {d.actor} · {relativeTime(d.created_at)}
                {d.undone_at && ` · undone ${relativeTime(d.undone_at)}`}
              </p>
            </div>
            {me.can_change_access && d.undoable && (
              <button className="btn btn--ghost btn--sm" onClick={() => undo(d.id)}>
                Undo
              </button>
            )}
          </li>
        ))}
      </ol>
      {decisions.data?.length === 0 && <Empty title="No changes yet.">Trims, suspensions and approvals will be listed here.</Empty>}
    </div>
  );
}
