import { useState, type FormEvent } from "react";

import { api, ApiError, tokenStore } from "../api";
import { Mark } from "../components/Bits";
import type { Me } from "../types";

export function SignIn({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = token.trim();
    if (!value) {
      setError("Paste the access token your administrator gave you.");
      return;
    }
    setBusy(true);
    setError(null);
    tokenStore.set(value);
    try {
      const me = await api.me();
      if (me.role === "service") {
        tokenStore.clear();
        setError("This is a machine token. Sign in with an admin or reviewer token.");
        return;
      }
      onSignedIn(me);
    } catch (err) {
      tokenStore.clear();
      setError(err instanceof ApiError && err.status === 401 ? "That token isn't valid." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <div className="signin__panel">
        <div className="brand brand--large">
          <Mark />
          <span>trim</span>
        </div>
        <p className="signin__lede">
          Every AI agent gets the keys it actually uses, <em>and nothing more.</em>
        </p>
        <form onSubmit={submit} noValidate>
          <label htmlFor="token">Access token</label>
          <input
            id="token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              setError(null);
            }}
            placeholder="trim_…"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "token-error" : undefined}
          />
          {error && (
            <p id="token-error" className="field-error">
              {error}
            </p>
          )}
          <button className="btn btn--ink" type="submit" disabled={busy}>
            {busy ? "Checking…" : "Sign in"}
          </button>
        </form>
        <p className="signin__foot">
          Create a token with <code>trim token create --name you --role admin</code>. It stays in this tab only.
        </p>
      </div>
      <div className="signin__art" aria-hidden="true">
        {["mail.full", "drive", "calendar", "contacts", "spreadsheets", "admin.directory.user"].map((s, i) => (
          <div key={s} className={`signin__row signin__row--${i % 3}`}>
            <span className="mono">{s}</span>
            <span className="signin__cut" />
          </div>
        ))}
      </div>
    </div>
  );
}
