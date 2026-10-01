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

export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M5 16h10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <path d="M20 16h7" stroke="var(--cut)" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 3" />
      <path d="M17.5 8v16" stroke="var(--cut)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
