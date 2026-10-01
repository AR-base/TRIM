import type { AgentState } from "./types";

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "unknown";
  const s = Math.round((now.getTime() - t) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  const fmt = (v: number, u: string) => (future ? `in ${plural(v, u)}` : `${plural(v, u)} ago`);
  if (a < 45) return future ? "in a moment" : "just now";
  if (a < 3600) return fmt(Math.round(a / 60), "minute");
  if (a < 86400) return fmt(Math.round(a / 3600), "hour");
  if (a < 86400 * 45) return fmt(Math.round(a / 86400), "day");
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function shortDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export const STATE_LABEL: Record<AgentState, string> = {
  learning: "Learning",
  ready: "Can be trimmed",
  trimmed: "Trimmed",
  right_sized: "Right-sized",
  exempt: "Exempt",
  suspended: "Suspended",
};

export const STATE_HINT: Record<AgentState, string> = {
  learning: "Watching what it uses before recommending anything",
  ready: "Holds permissions it never used",
  trimmed: "Trim removed what it did not use",
  right_sized: "Uses everything it holds",
  exempt: "Excluded from recommendations by an admin",
  suspended: "All access removed",
};

export const RISK_LABEL = ["None", "Low", "Medium", "High"] as const;

export function riskLabel(r: number): string {
  return RISK_LABEL[Math.max(0, Math.min(3, r))] ?? "Medium";
}

export const ACTION_LABEL: Record<string, string> = {
  trim: "Trimmed",
  suspend: "Suspended",
  restore: "Restored",
  grant_once: "Allowed once",
  grant_always: "Allowed always",
  expire: "Temporary access ended",
};
