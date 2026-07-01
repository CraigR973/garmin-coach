import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { colors } from '@/theme/tokens';
import { buildChartSeries, mutedSpans } from '@/lib/bedroomChart';
import type { BedroomOvernightData } from '@/hooks/useBedroomOvernight';

// Faint hypnogram band colours by Garmin sleep stage.
const STAGE_FILL: Record<string, string> = {
  deep: colors.primaryDark,
  light: colors.steeleDark,
  rem: colors.accent,
  awake: colors.error,
  unknown: colors.border,
};

function ms(iso: string): number {
  return new Date(iso).getTime();
}

function fmtClock(value: number): string {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function BedroomOvernightChart({ data }: { data: BedroomOvernightData }) {
  const hasData = data.temperature.length > 0 || data.fan.length > 0;
  if (!hasData) {
    return (
      <p data-testid="overnight-empty" className="py-8 text-center text-sm text-text-muted">
        No room or fan data for this night yet. The fan track starts recording from the day this
        was deployed; earlier nights show temperature and sleep only.
      </p>
    );
  }

  const series = buildChartSeries(data.temperature, data.fan);
  const muted = mutedSpans(data.fan);
  const startMs = ms(data.windowStartUtc);
  const endMs = ms(data.windowEndUtc);

  const temps = data.temperature.map((p) => p.c);
  const yLow = Math.floor(Math.min(data.thresholds.onC, ...(temps.length ? temps : [18])) - 1);
  const yHigh = Math.ceil(Math.max(data.thresholds.criticalC, ...(temps.length ? temps : [22])) + 1);

  const stages = data.sleep?.stages ?? [];
  const sleepWindow = data.sleep?.start && data.sleep?.end ? data.sleep : null;

  return (
    <div data-testid="overnight-chart" className="space-y-3">
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />

          {/* Sleep behind everything: the hypnogram band if present, else the window. */}
          {stages.length > 0
            ? stages.map((stage, i) => (
                <ReferenceArea
                  key={`stage-${i}`}
                  yAxisId="temp"
                  x1={ms(stage.start)}
                  x2={ms(stage.end)}
                  fill={STAGE_FILL[stage.stage] ?? colors.border}
                  fillOpacity={0.1}
                  stroke="none"
                />
              ))
            : sleepWindow
              ? (
                  <ReferenceArea
                    yAxisId="temp"
                    x1={ms(sleepWindow.start as string)}
                    x2={ms(sleepWindow.end as string)}
                    fill={colors.primary}
                    fillOpacity={0.06}
                    stroke="none"
                  />
                )
              : null}

          {/* Explained fan gaps (autopilot off / cloud unreachable). */}
          {muted.map((span, i) => (
            <ReferenceArea
              key={`muted-${i}`}
              yAxisId="fan"
              x1={span.start}
              x2={span.end}
              fill={colors.locked}
              fillOpacity={0.14}
              stroke="none"
            />
          ))}

          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[startMs, endMs]}
            tickFormatter={fmtClock}
            tick={{ fill: colors.textMuted, fontSize: 11 }}
            stroke={colors.border}
          />
          <YAxis
            yAxisId="temp"
            domain={[yLow, yHigh]}
            tick={{ fill: colors.textMuted, fontSize: 11 }}
            stroke={colors.border}
            width={40}
            unit="°"
          />
          <YAxis
            yAxisId="fan"
            orientation="right"
            domain={[0, 7]}
            ticks={[0, 3, 5, 7]}
            tick={{ fill: colors.textMuted, fontSize: 11 }}
            stroke={colors.border}
            width={24}
          />

          <ReferenceLine
            yAxisId="temp"
            y={data.thresholds.onC}
            stroke={colors.warning}
            strokeDasharray="4 4"
          />
          <ReferenceLine
            yAxisId="temp"
            y={data.thresholds.criticalC}
            stroke={colors.error}
            strokeDasharray="4 4"
          />

          <Tooltip
            labelFormatter={(value) => fmtClock(Number(value))}
            contentStyle={{
              background: 'var(--surface-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              color: 'var(--text-primary)',
            }}
          />

          <Area
            yAxisId="fan"
            type="stepAfter"
            dataKey="speed"
            name="Fan speed"
            stroke={colors.accent}
            fill={colors.accent}
            fillOpacity={0.16}
            connectNulls={false}
            dot={false}
          />
          <Line
            yAxisId="temp"
            type="monotone"
            dataKey="c"
            name="Room °C"
            stroke={colors.primary}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>

      <ChartLegend hasSleep={stages.length > 0 || Boolean(sleepWindow)} muted={muted} />
    </div>
  );
}

function ChartLegend({
  hasSleep,
  muted,
}: {
  hasSleep: boolean;
  muted: ReturnType<typeof mutedSpans>;
}) {
  const mutedLabels = [...new Set(muted.map((span) => span.label))];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
      <LegendDot color={colors.primary} label="Room °C" />
      <LegendDot color={colors.accent} label="Fan speed" />
      <span className="text-text-muted/80">Lines: fan on 19.5° · critical 20.0°</span>
      {hasSleep ? <LegendDot color={colors.primaryDark} label="Asleep" /> : null}
      {mutedLabels.map((label) => (
        <LegendDot key={label} color={colors.locked} label={label} />
      ))}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}
