import type { PowerBar } from '@/lib/structuredWorkout';

/**
 * SVG power-profile preview for a structured ride. Shared (Batch 135) by the
 * free-form editor (StructuredWorkoutSheet) and the read-only detail sheet
 * (WorkoutDetailSheet) so both draw the ride shape identically. Steady bars are
 * rectangles; ramps are trapezoids; the dashed line marks 100% FTP.
 */
export function PowerProfilePreview({
  bars,
  totalMin,
  peakPct,
}: {
  bars: PowerBar[];
  totalMin: number;
  peakPct: number;
}) {
  if (bars.length === 0 || totalMin <= 0) {
    return (
      <div className="rounded-lg border border-border p-3 text-center text-xs text-text-secondary">
        Fill in the segments to preview the ride.
      </div>
    );
  }
  const height = 120;
  const yMax = Math.max(150, peakPct);
  const y = (pct: number) => height - (Math.max(0, pct) / yMax) * height;
  let cursor = 0;
  const shapes = bars.map((bar, index) => {
    const x = cursor;
    const width = bar.durationMin;
    cursor += width;
    const opacity = Math.min(0.95, Math.max(0.3, 0.3 + (Math.max(bar.startPct, bar.endPct) / 200) * 0.6));
    if (bar.startPct === bar.endPct) {
      return (
        <rect
          key={index}
          x={x}
          y={y(bar.startPct)}
          width={width}
          height={height - y(bar.startPct)}
          fill="currentColor"
          opacity={opacity}
        />
      );
    }
    const points = `${x},${height} ${x},${y(bar.startPct)} ${x + width},${y(bar.endPct)} ${x + width},${height}`;
    return <polygon key={index} points={points} fill="currentColor" opacity={opacity} />;
  });
  return (
    <div className="space-y-1">
      <div className="text-primary">
        <svg
          viewBox={`0 0 ${totalMin} ${height}`}
          preserveAspectRatio="none"
          className="h-24 w-full rounded-lg bg-surface-muted"
          role="img"
          aria-label="Power profile preview"
        >
          {shapes}
          <line
            x1={0}
            x2={totalMin}
            y1={y(100)}
            y2={y(100)}
            stroke="currentColor"
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.5}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div className="flex justify-between text-xs text-text-secondary">
        <span>Total {totalMin} min</span>
        <span>Peak {peakPct}% FTP · dashed = 100%</span>
      </div>
    </div>
  );
}
