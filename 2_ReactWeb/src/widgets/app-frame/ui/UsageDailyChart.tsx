import { useState } from "react";
import type { DailyStatistic } from "../../../services/workspace/getWorkspaceStatistics";
import { formatStatistic } from "../model/statisticFormatting";

type Props = { daily: DailyStatistic[]; duration: boolean; language: string; label: string };

export function UsageDailyChart({ daily, duration, language, label }: Props) {
  const [activeDate, setActiveDate] = useState<string | null>(null);
  const active = daily.find(day => day.date === activeDate);
  const maximum = Math.max(1, ...daily.map(day => day.value));
  const magnitude = 10 ** Math.floor(Math.log10(maximum));
  const ceiling = Math.ceil(maximum / magnitude) * magnitude;
  const left = 42, top = 10, width = 350, height = 76;
  const step = width / Math.max(daily.length, 1);
  const number = (value: number, compact = false) => formatStatistic(value, duration, language, compact);
  return (
    <div className="usage-daily-chart">
      <div className="usage-daily-chart__detail" aria-live="polite">
        {active ? `${active.date} · ${number(active.value)}` : "\u00a0"}
      </div>
      <svg viewBox="0 0 404 110" role="group" aria-label={label}>
        {[0, 0.5, 1].map(fraction => {
          const y = top + height * (1 - fraction);
          return <g key={fraction} aria-hidden="true">
            <line x1={left} x2={left + width} y1={y} y2={y} className="usage-daily-chart__grid" />
            <text x={left - 6} y={y + 3} textAnchor="end">{number(ceiling * fraction, true)}</text>
          </g>;
        })}
        {daily.map((day, index) => {
          const x = left + index * step;
          const barHeight = day.value > 0 ? Math.max(1, day.value / ceiling * height) : 0;
          const dayNumber = index + 1;
          const showLabel = index === 0 || dayNumber === daily.length || (dayNumber % 5 === 0 && daily.length - dayNumber >= 3);
          const description = `${day.date} · ${number(day.value)}`;
          return <g key={day.date} tabIndex={0} role="img" aria-label={description}
            onMouseEnter={() => setActiveDate(day.date)} onMouseLeave={() => setActiveDate(null)}
            onFocus={() => setActiveDate(day.date)} onBlur={() => setActiveDate(null)}>
            <title>{description}</title>
            <rect x={x} y={top} width={step} height={height} fill="transparent" />
            <rect className="usage-daily-chart__bar" x={x + 2} y={top + height - barHeight}
              width={Math.max(1, step - 4)} height={barHeight} rx={2} />
            {showLabel ? <text x={x + step / 2} y={top + height + 17} textAnchor="middle" aria-hidden="true">{dayNumber}</text> : null}
          </g>;
        })}
      </svg>
    </div>
  );
}
