import { shortDate } from "../format";

interface Props {
  days: { day: string; calls: number }[];
  flagged?: string[];
  excluded?: string[];
  windowStart?: string;
  height?: number;
}

/** 28 days of API calls as bars; alert days in vermilion, days left out of the recommendation hatched. */
export function ActivityBars({ days, flagged = [], excluded = [], windowStart, height = 72 }: Props) {
  const max = Math.max(1, ...days.map((d) => d.calls));
  const flaggedSet = new Set(flagged);
  const excludedSet = new Set(excluded);
  const windowDay = windowStart?.slice(0, 10);
  const total = days.reduce((a, d) => a + d.calls, 0);
  return (
    <figure className="bars" aria-label={`${total} API calls over ${days.length} days`}>
      <div className="bars__plot" style={{ height }}>
        {days.map((d) => {
          const h = d.calls === 0 ? 2 : Math.max(3, (d.calls / max) * height);
          const cls = flaggedSet.has(d.day) ? "bars__bar--alert" : excludedSet.has(d.day) ? "bars__bar--excluded" : "";
          const inWindow = !windowDay || d.day >= windowDay;
          return (
            <span
              key={d.day}
              className={`bars__bar ${cls} ${inWindow ? "" : "bars__bar--before"}`}
              style={{ height: h }}
              title={`${shortDate(d.day)}: ${d.calls} calls`}
            />
          );
        })}
      </div>
      {days.length > 0 && (
        <figcaption className="bars__axis">
          <span>{shortDate(days[0]!.day)}</span>
          {windowDay && <span className="bars__window">observation window →</span>}
          <span>{shortDate(days[days.length - 1]!.day)}</span>
        </figcaption>
      )}
    </figure>
  );
}
