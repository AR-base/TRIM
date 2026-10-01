import type {
  AgentDetail,
  AgentState,
  AgentSummary,
  AlertView,
  Capability,
  DecisionView,
  Me,
  RequestView,
  Summary,
  TrimAllResult,
} from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "trim.token";

/** An error the API explained: `code` is machine-readable, `message` is safe to show. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// The token lives in sessionStorage: it is gone when the tab closes and never shared across tabs.
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage blocked: the session simply will not persist */
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

type Fetcher = typeof fetch;

export function createClient(fetcher: Fetcher = (...a) => fetch(...a), getToken = tokenStore.get) {
  async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetcher(`${BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "omit",
        redirect: "error",
      });
    } catch {
      throw new ApiError(0, "network", "Trim's server can't be reached. Check your connection.");
    }
    const text = await res.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!res.ok) {
      const err = (data ?? {}) as { error?: string; detail?: string };
      throw new ApiError(res.status, err.error ?? `http_${res.status}`, err.detail ?? res.statusText ?? "Request failed");
    }
    return data as T;
  }

  const q = (params: Record<string, string | number | undefined | null>) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
    const s = sp.toString();
    return s ? `?${s}` : "";
  };

  return {
    me: () => request<Me>("GET", "/me"),
    summary: () => request<Summary>("GET", "/summary"),
    capabilities: () => request<Capability[]>("GET", "/capabilities"),
    agents: (p: { state?: AgentState | ""; q?: string; can?: string } = {}) =>
      request<AgentSummary[]>("GET", `/agents${q(p)}`),
    agent: (id: number) => request<AgentDetail>("GET", `/agents/${id}`),
    trim: (id: number, confirmRevoke = false) =>
      request<DecisionView>("POST", `/agents/${id}/trim`, { confirm_revoke: confirmRevoke }),
    trimAll: (confirmRevoke = false) =>
      request<TrimAllResult>("POST", "/agents/trim-all", { confirm_revoke: confirmRevoke }),
    suspend: (id: number, reason = "") => request<DecisionView>("POST", `/agents/${id}/suspend`, { reason }),
    exempt: (id: number, exempt: boolean) => request<{ exempt: boolean }>("POST", `/agents/${id}/exempt`, { exempt }),
    decisions: (agentId?: number) => request<DecisionView[]>("GET", `/decisions${q({ agent_id: agentId })}`),
    undo: (id: number) => request<DecisionView>("POST", `/decisions/${id}/undo`),
    alerts: (status?: string) => request<AlertView[]>("GET", `/alerts${q({ status })}`),
    reviewAlert: (id: number, status: "confirmed" | "dismissed") =>
      request<AlertView>("POST", `/alerts/${id}/review`, { status }),
    requests: (status?: string) => request<RequestView[]>("GET", `/requests${q({ status })}`),
    decide: (id: number, choice: "allow_once" | "allow_always" | "deny", minutes?: number) =>
      request<RequestView>("POST", `/requests/${id}/decide`, minutes ? { choice, minutes } : { choice }),
    sync: () => request<Record<string, unknown>>("POST", "/sync"),
  };
}

export type Api = ReturnType<typeof createClient>;
export const api = createClient();
