import { useState, type CSSProperties, type FormEvent } from "react";

import { api, ApiError, tokenStore } from "../api";
import { Mark } from "../components/Bits";
import type { Me } from "../types";
import "@fontsource-variable/schibsted-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./signin.css";

/** One real-looking agent from the test organisation, used to show what Trim does before signing in. */
const EXAMPLE = [
  { what: "Read all email", scope: "gmail.readonly", calls: 1284 },
  { what: "Write drafts and send email", scope: "gmail.compose", calls: 96 },
  { what: "Permanently delete email", scope: "mail.google.com", calls: 0 },
  { what: "Edit and share every Drive file", scope: "drive", calls: 0 },
  { what: "Manage and share every calendar", scope: "calendar", calls: 0 },
];
const MAX_CALLS = Math.max(...EXAMPLE.map((r) => r.calls));
const CUT_COUNT = EXAMPLE.filter((r) => r.calls === 0).length;

export function SignIn({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [token, setToken] = useState("");
  const [visible, setVisible] = useState(false);
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
    <div className="login">
      <section className="login__side">
        <div className="brand brand--large">
          <Mark />
          <span>trim</span>
        </div>

        <div className="login__main">
          <h1 className="login__title">Every AI agent keeps only the access it uses.</h1>
          <p className="login__lede">
            Trim watches what each agent does with its permissions and removes the ones it never touches.
          </p>

          <form className="login__form" onSubmit={submit} noValidate>
            <label htmlFor="token">Access token</label>
            <div className={`login__field${error ? " login__field--invalid" : ""}`}>
              <input
                id="token"
                type={visible ? "text" : "password"}
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
              <button
                type="button"
                className="login__reveal"
                onClick={() => setVisible((v) => !v)}
                aria-pressed={visible}
                aria-controls="token"
              >
                {visible ? "Hide" : "Show"}
              </button>
            </div>
            {error && (
              <p id="token-error" className="field-error" role="alert">
                {error}
              </p>
            )}
            <button className="btn btn--ink login__submit" type="submit" disabled={busy}>
              {busy ? "Checking…" : "Sign in"}
            </button>
          </form>
        </div>

        <p className="login__note">Your token stays in this browser tab and is forgotten when you close it.</p>
      </section>

      <section className="login__stage" aria-label="Example of Trim at work">
        <figure className="ledger">
          <figcaption className="ledger__head">
            <span className="ledger__name">Inbox Copilot</span>
            <span className="ledger__meta">Connected by 6 people, activity from the last 14 days</span>
          </figcaption>

          <ul className="ledger__rows">
            {EXAMPLE.map((r, i) => {
              const cut = r.calls === 0;
              return (
                <li
                  key={r.scope}
                  className={`ledger__row${cut ? " ledger__row--cut" : ""}`}
                  style={{ "--i": i } as CSSProperties}
                >
                  <span className="ledger__what">
                    <span className="ledger__label">
                      <span className="ledger__text">{r.what}</span>
                    </span>
                    <code>{r.scope}</code>
                  </span>
                  {cut ? (
                    <span className="ledger__never">Never used</span>
                  ) : (
                    <span className="ledger__use">
                      <span
                        className="ledger__bar"
                        style={{ "--w": Math.max(0.06, r.calls / MAX_CALLS) } as CSSProperties}
                      />
                      <span className="ledger__calls">{r.calls.toLocaleString("en-GB")} calls</span>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>

          <div className="ledger__reach">
            <p className="reach reach--before">
              <span className="reach__label">Today</span>
              Can delete all email, edit and share every Drive file, and manage every calendar.
            </p>
            <p className="reach reach--after">
              <span className="reach__label">After trim</span>
              Can read all email, write drafts and send email.
            </p>
          </div>
        </figure>
        <p className="login__caption">
          An agent from the test organisation. Trim removed the {CUT_COUNT} permissions it never used.
        </p>
      </section>
    </div>
  );
}
