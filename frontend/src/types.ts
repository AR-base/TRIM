// Mirrors trim/api/schemas.py.

export type AgentState = "learning" | "ready" | "trimmed" | "right_sized" | "exempt" | "suspended";
export type ScopeStatus = "used" | "narrowed" | "unused" | "learning";

export interface AgentSummary {
  id: number;
  name: string;
  client_id: string;
  owner_email: string;
  state: AgentState;
  reach: string;
  users: number;
  granted: number;
  unused: number;
  risk: number;
  open_alerts: number;
  last_activity: string | null;
  first_seen: string;
}

export interface ScopeView {
  scope: string;
  short: string;
  phrase: string;
  risk: number;
  status: ScopeStatus;
  narrowed_to: string[];
  users: number;
  essential: boolean;
}

export interface GrantView {
  user_email: string;
  granted: string[];
  keep: string[];
  remove: string[];
  calls: number;
  reasons: Record<string, string[]>;
}

export interface AlertReason {
  feature: string;
  z: number;
  text: string;
}

export interface AlertView {
  id: number;
  agent_id: number;
  agent_name: string;
  day: string;
  score: number;
  status: "open" | "confirmed" | "dismissed";
  reasons: AlertReason[];
  created_at: string;
}

export interface DecisionView {
  id: number;
  action: "trim" | "suspend" | "restore" | "grant_once" | "grant_always" | "expire";
  agent_id: number;
  agent_name: string;
  actor: string;
  reason: string;
  created_at: string;
  undone_at: string | null;
  undo_of_id: number | null;
  before: Record<string, string[]>;
  after: Record<string, string[]>;
  removed: number;
  added: number;
  undoable: boolean;
}

export interface AgentDetail extends AgentSummary {
  reach_after: string;
  learning_until: string | null;
  window_start: string;
  window_end: string;
  calls: number;
  dormant: boolean;
  excluded_days: string[];
  scopes: ScopeView[];
  grants: GrantView[];
  alerts: AlertView[];
  decisions: DecisionView[];
  activity: { day: string; calls: number }[];
  can_narrow: boolean;
  can_restore: boolean;
}

export interface RequestView {
  id: number;
  agent_id: number;
  agent_name: string;
  user_email: string;
  scopes: string[];
  phrases: string[];
  justification: string;
  status: "pending" | "approved_once" | "approved_always" | "denied" | "expired";
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string | null;
}

export interface Summary {
  agents: number;
  users: number;
  active_grants: number;
  by_state: Record<AgentState, number>;
  unused_permissions: number;
  granted_permissions: number;
  high_risk_agents: number;
  open_alerts: number;
  pending_requests: number;
  last_sync: string | null;
  provider: string;
  can_narrow: boolean;
  can_restore: boolean;
}

export interface Me {
  name: string;
  role: "admin" | "reviewer" | "service";
  can_change_access: boolean;
}

export interface Capability {
  key: string;
  label: string;
}

export interface TrimAllResult {
  trimmed: { agent_id: number; decision_id: number }[];
  skipped: { agent_id: number; error: string; detail: string }[];
}
