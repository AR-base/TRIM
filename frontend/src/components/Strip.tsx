import type { ScopeView } from "../types";

const WEIGHT = [1, 1, 2, 3];

/**
 * The permission strip: one segment per granted permission, sized by risk.
 * Solid = used, notched = narrowed to something smaller, hatched with a cut line = unused.
 */
export function PermissionStrip({ scopes, compact = false }: { scopes: ScopeView[]; compact?: boolean }) {
  // Sign-in scopes (openid, email) are always needed and never trimmed, so they are not drawn.
  const visible = scopes.filter((s) => !s.essential);
  if (visible.length === 0) return <div className="strip strip--empty" aria-label="No permissions" />;
  const label = visible
    .map((s) => `${s.short}: ${s.status === "used" ? "in use" : s.status === "narrowed" ? "can be narrowed" : s.status}`)
    .join(", ");
  return (
    <div className={`strip${compact ? " strip--compact" : ""}`} role="img" aria-label={label}>
      {visible.map((s) => (
        <span
          key={s.scope}
          className={`strip__seg strip__seg--${s.status}`}
          style={{ flexGrow: WEIGHT[s.risk] ?? 2 }}
          title={`${s.short} · ${s.phrase}`}
          data-status={s.status}
        >
          {!compact && <span className="strip__label">{s.short}</span>}
        </span>
      ))}
    </div>
  );
}

/** A compact strip for list rows, where only counts are known. */
export function CountStrip({ granted, unused }: { granted: number; unused: number }) {
  const used = Math.max(granted - unused, 0);
  return (
    <div className="strip strip--compact" role="img" aria-label={`${used} in use, ${unused} unused`}>
      {used > 0 && <span className="strip__seg strip__seg--used" style={{ flexGrow: used }} />}
      {unused > 0 && <span className="strip__seg strip__seg--unused" style={{ flexGrow: unused }} />}
    </div>
  );
}
