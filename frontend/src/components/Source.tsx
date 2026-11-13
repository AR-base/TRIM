import { useState } from "react";

import { useSession } from "../App";
import { ApiError } from "../api";
import { plural, relativeTime, shortDate } from "../format";
import type { AgentDetail, Summary } from "../types";
import { useToast } from "./Toast";

/** Human name of the system Trim reads agents from. */
export function providerName(provider: string): string {
  if (provider === "google") return "Google Workspace";
  if (provider === "simulated") return "Google Workspace (simulated demo tenant)";
  return provider;
}

/** When the worker will look again, from the last sync and the configured interval. */
export function nextSync(summary: Pick<Summary, "last_sync" | "sync_interval_minutes">, now: Date = new Date()): string {
  if (!summary.last_sync) return "at the next worker cycle";
  const due = new Date(summary.last_sync).getTime() + summary.sync_interval_minutes * 60_000;
  if (Number.isNaN(due) || due <= now.getTime()) return "any moment now";
  return relativeTime(new Date(due).toISOString(), now);
}

/** Runs one sync cycle now instead of waiting for the worker; admins only. */
export function SyncButton({ onDone, size }: { onDone?: () => Promise<unknown> | void; size?: "sm" }) {
  const { api, me, refreshSummary } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!me.can_change_access) return null;

  async function run() {
    setBusy(true);
    try {
      const r = await api.sync();
      const s = r.sync;
      const parts = [
        `${plural(s.users, "person", "people")} checked`,
        s.agents_new ? `${plural(s.agents_new, "new agent")} found` : "no new agents",
        `${plural(s.events_new, "new call")}`,
      ];
      toast({
        tone: s.errors.length ? "error" : "ok",
        text: s.errors.length ? `Synced with errors: ${s.errors[0]}` : `Synced: ${parts.join(", ")}.`,
      });
      await Promise.all([refreshSummary(), onDone?.()]);
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.message : "Sync failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className={`btn btn--ghost${size === "sm" ? " btn--sm" : ""}`} onClick={run} disabled={busy} aria-busy={busy}>
      <span className={`syncicon${busy ? " syncicon--spin" : ""}`} aria-hidden="true" />
      {busy ? "Syncing…" : "Sync now"}
    </button>
  );
}

/** Overview panel: where the agents come from, and how fresh the picture is. */
export function ConnectionPanel({ summary, onSynced }: { summary: Summary; onSynced?: () => Promise<unknown> | void }) {
  const simulated = summary.provider === "simulated";
  const steps = [
    {
      n: "01",
      title: "A person authorises an agent",
      body: "Someone in the company clicks Allow. Google gives the agent's OAuth client ID a token with the permissions it asked for.",
    },
    {
      n: "02",
      title: "Google keeps every token",
      body: "For each user, the Directory API lists which apps hold a token and with which permissions.",
      api: "directory.tokens.list",
    },
    {
      n: "03",
      title: `Trim reads it every ${summary.sync_interval_minutes} min`,
      body: `It also reads the token audit log: every API call each client ID made, going back ${summary.lookback_hours} hours because Google's logs arrive late.`,
      api: "reports.activities · token",
    },
    {
      n: "04",
      title: "Each client ID becomes an agent here",
      body: `${plural(summary.agents, "agent")} found across ${plural(summary.users, "person", "people")}. Agents that existed before Trim appear at the first sync; new ones at the next.`,
    },
  ];

  return (
    <section className="panel source" aria-labelledby="source-title">
      <div className="source__head">
        <div>
          <p className="eyebrow">How Trim sees your agents</p>
          <h2 id="source-title" className="source__title">
            <span className="source__dot" aria-hidden="true" />
            Connected to Google Workspace
            {simulated && <span className="source__tag mono">Simulated demo tenant</span>}
          </h2>
          <p className="muted">
            Nothing is installed on the agents. Trim reads the tokens Google already holds, with a read-only service account
            (3 admin permissions: list users, list and revoke tokens, read the token audit log).
          </p>
        </div>
        <div className="source__sync">
          <dl className="source__times">
            <div>
              <dt>Last sync</dt>
              <dd>{relativeTime(summary.last_sync)}</dd>
            </div>
            <div>
              <dt>Next automatic sync</dt>
              <dd>{nextSync(summary)}</dd>
            </div>
          </dl>
          <SyncButton onDone={onSynced} />
        </div>
      </div>

      <ol className="flow">
        {steps.map((s) => (
          <li key={s.n} className="flow__step">
            <span className="flow__n mono">{s.n}</span>
            <p className="flow__title">{s.title}</p>
            <p className="flow__body">{s.body}</p>
            {s.api && <code className="flow__api">{s.api}</code>}
          </li>
        ))}
      </ol>

      <p className="source__foot">
        <b>Trimming</b> revokes the agent's token at Google (<code>directory.tokens.delete</code>). Trim applies and records the
        change at once, in History; Google's own confirmation comes back with the next sync.
        {simulated && " In this demo, a simulator answers the same API calls with a company of synthetic people and agents."}
      </p>
    </section>
  );
}

/** Agent page panel: the evidence that ties this agent to real tokens and calls. */
export function AgentSource({ agent, provider }: { agent: AgentDetail; provider: string }) {
  const people = agent.grants.map((g) => g.user_email);
  const shown = people.slice(0, 5);
  return (
    <section className="panel source source--agent" aria-labelledby="agent-source-title">
      <h2 id="agent-source-title" className="panel__title">
        How Trim found this agent
      </h2>
      <dl className="facts">
        <div>
          <dt>OAuth client ID</dt>
          <dd className="mono">{agent.client_id}</dd>
        </div>
        <div>
          <dt>Found in</dt>
          <dd>
            {provider === "google" ? "Google's" : "The demo tenant's"} token list of {plural(agent.users, "person", "people")}
            {shown.length > 0 && (
              <span className="facts__sub">
                {shown.join(", ")}
                {people.length > shown.length && ` and ${people.length - shown.length} more`}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>First seen</dt>
          <dd>{shortDate(agent.first_seen)}</dd>
        </div>
        <div>
          <dt>Calls observed</dt>
          <dd>
            {plural(agent.calls, "call")} in the last 14 days · last {relativeTime(agent.last_activity)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
