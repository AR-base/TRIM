import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError, tokenStore } from "../api";
import { Mark } from "../components/Bits";
import type { Me } from "../types";
import "./signin.css";

/** One real-looking agent from the test organisation, used to show what Trim does before signing in. */
const EXAMPLE = [
  { what: "Read all email", scope: "gmail.readonly", calls: 1284 },
  { what: "Write drafts and send email", scope: "gmail.compose", calls: 96 },
  { what: "Permanently delete email", scope: "mail.google.com", calls: 0 },
  { what: "Edit and share every Drive file", scope: "drive", calls: 0 },
  { what: "Manage and share every calendar", scope: "calendar", calls: 0 },
];
const CUT_COUNT = EXAMPLE.filter((r) => r.calls === 0).length;

function hasWebGL(): boolean {
  return typeof window !== "undefined" && ("WebGL2RenderingContext" in window || "WebGLRenderingContext" in window);
}

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
      <div className="login__cols" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>

      <section className="login__side">
        <div className="brand brand--large">
          <Mark />
          <span>Trim</span>
        </div>

        <div className="login__main">
          <p className="login__eyebrow">Least privilege for AI agents</p>
          <h1 className="login__title">
            Keeper of the <em>keys</em>
          </h1>
          <p className="login__lede">
            Trim watches what every AI agent does with its permissions and takes back the ones it never touches.
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
            <button className="btn btn--ink btn--lg login__submit" type="submit" disabled={busy}>
              {busy ? "Checking…" : "Sign in"}
            </button>
          </form>
        </div>

        <p className="login__note">Your token stays in this browser tab and is forgotten when you close it.</p>
      </section>

      <section className="login__stage" aria-label="Example of Trim at work">
        <Keeper />
        <figure className="verdict">
          <figcaption className="verdict__head">
            <span className="verdict__name">Inbox Copilot</span>
            <span className="verdict__meta">6 people · last 14 days</span>
          </figcaption>
          <ul className="verdict__rows">
            {EXAMPLE.map((r) => (
              <li key={r.scope} className={`verdict__row${r.calls === 0 ? " verdict__row--cut" : ""}`}>
                <span className="verdict__what">{r.what}</span>
                <span className="verdict__calls">{r.calls === 0 ? "Never used" : `${r.calls.toLocaleString("en-GB")} calls`}</span>
              </li>
            ))}
          </ul>
          <p className="verdict__foot">Trim removed the {CUT_COUNT} permissions it never used.</p>
        </figure>
      </section>
    </div>
  );
}

/** The 3D character. Shows a still version until WebGL has drawn, and stays on it without WebGL. */
function Keeper() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const labels = labelsRef.current;
    if (!canvas || !labels || !hasWebGL()) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    import("../stage/keeper")
      .then(({ mountKeeper }) => {
        if (cancelled) return;
        dispose = mountKeeper(canvas, labels, {
          keys: EXAMPLE.map((r) => ({ scope: r.scope, kept: r.calls > 0 })),
          reducedMotion,
          onReady: () => setLive(true),
          onLost: () => setLive(false),
        });
      })
      .catch(() => setLive(false));
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, []);

  return (
    <div className={`keeper${live ? " keeper--live" : ""}`} aria-hidden="true">
      <div className="keeper__still">
        <i className="keeper__ring" />
        <i className="keeper__body" />
        <i className="keeper__head" />
      </div>
      <canvas ref={canvasRef} className="keeper__canvas" />
      <div ref={labelsRef} className="keeper__labels" />
    </div>
  );
}
