import { riskLabel, STATE_HINT, STATE_LABEL } from "../format";
import type { AgentState } from "../types";

export function StateBadge({ state }: { state: AgentState }) {
  return (
    <span className={`badge badge--${state}`} title={STATE_HINT[state]}>
      {STATE_LABEL[state]}
    </span>
  );
}

export function RiskDots({ risk }: { risk: number }) {
  return (
    <span className="risk" aria-label={`${riskLabel(risk)} risk`} title={`${riskLabel(risk)} risk`}>
      {[1, 2, 3].map((i) => (
        <i key={i} className={i <= risk ? `risk__dot risk__dot--on risk__dot--${risk}` : "risk__dot"} />
      ))}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {children && <p className="empty__body">{children}</p>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="note note--error" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button className="btn btn--ghost btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** The Keeper's halo with its line of light: Trim's mark. */
export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9.5 16.5h13" stroke="var(--signal)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
