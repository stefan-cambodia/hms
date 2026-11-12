/**
 * Small SVG charts following the data-visualisation rules of the project:
 * one axis only, thin marks (2px lines, bars at most 24px with a 4px rounded
 * data end, square at the baseline), a 2px surface gap between stacked
 * segments and a 2px surface ring on markers, hairline solid grid, a legend
 * whenever there are two series, a crosshair or per-bar tooltip (also on
 * keyboard focus), and text in text colours (never in the series colour).
 * Colours are roles defined in styles.css (--viz-*), validated for colour
 * vision deficiency in light and dark mode.
 */
import { type KeyboardEvent, type ReactNode, useMemo, useState } from 'react';
import { Box, Group, Paper, Text } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';

export type Tone = 'accent' | 'muted';
const COLOR: Record<Tone, string> = { accent: 'var(--viz-accent)', muted: 'var(--viz-muted)' };

const M = { top: 12, right: 16, bottom: 26 };

/** Left margin wide enough for the longest y-axis label (11px text). */
function leftMargin(ticks: number[], format: (v: number) => string): number {
  return Math.max(36, Math.ceil(Math.max(...ticks.map((t) => format(t).length)) * 6.6) + 14);
}

/** Round axis ticks: 0 .. a clean maximum in 4 or 5 steps. */
export function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => +(i * step).toFixed(10));
}

function xLabelIndexes(n: number, width: number): number[] {
  const fit = Math.max(2, Math.floor(width / 70));
  if (n <= fit) return Array.from({ length: n }, (_, i) => i);
  const step = Math.ceil(n / fit);
  return Array.from({ length: n }, (_, i) => i).filter((i) => i % step === 0);
}

export function Legend({ items, shape = 'line' }: { items: { label: string; tone: Tone }[]; shape?: 'line' | 'rect' }) {
  return (
    <Group gap="md" mb={6} role="list">
      {items.map((it) => (
        <Group key={it.label} gap={6} wrap="nowrap" role="listitem">
          <span
            aria-hidden
            style={{ display: 'inline-block', width: shape === 'line' ? 16 : 10, height: shape === 'line' ? 2 : 10, borderRadius: shape === 'line' ? 1 : 2, background: COLOR[it.tone] }}
          />
          <Text size="xs" c="dimmed">
            {it.label}
          </Text>
        </Group>
      ))}
    </Group>
  );
}

function Tooltip({ x, width, title, rows, top = 4 }: { x: number; width: number; title: string; rows: { label: string; value: string; tone?: Tone }[]; top?: number }) {
  const left = Math.min(Math.max(x + 12, 0), Math.max(width - 190, 0));
  return (
    <Paper shadow="md" p={8} radius="sm" withBorder style={{ position: 'absolute', top, left, minWidth: 150, pointerEvents: 'none', zIndex: 2 }}>
      <Text size="xs" c="dimmed" mb={2}>
        {title}
      </Text>
      {rows.map((r) => (
        <Group key={r.label} gap={8} wrap="nowrap" justify="space-between">
          <Group gap={6} wrap="nowrap">
            {r.tone && <span aria-hidden style={{ width: 12, height: 2, background: COLOR[r.tone], display: 'inline-block' }} />}
            <Text size="xs" c="dimmed">
              {r.label}
            </Text>
          </Group>
          <Text size="sm" fw={600} className="hms-num">
            {r.value}
          </Text>
        </Group>
      ))}
    </Paper>
  );
}

function keyboardHandler(n: number, setActive: (i: number | null) => void, active: number | null) {
  return (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setActive(Math.min(n - 1, (active ?? -1) + 1));
    else if (e.key === 'ArrowLeft') setActive(Math.max(0, (active ?? n) - 1));
    else if (e.key === 'Escape') setActive(null);
    else return;
    e.preventDefault();
  };
}

export interface LineSeries {
  label: string;
  tone: Tone;
  values: (number | null)[];
}

/** Line chart over time (one or two series; the second is the comparison). */
export function LineChart({
  labels,
  titles,
  series,
  format,
  height = 220,
  yMax,
  ariaLabel,
  area = false,
}: {
  labels: string[];
  titles: string[];
  series: LineSeries[];
  format: (v: number) => string;
  height?: number;
  yMax?: number;
  ariaLabel: string;
  area?: boolean;
}) {
  const { ref, width } = useElementSize();
  const [active, setActive] = useState<number | null>(null);
  const n = labels.length;
  const max = yMax ?? Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const ticks = useMemo(() => niceTicks(max), [max]);
  const top = ticks[ticks.length - 1] || 1;
  const ML = leftMargin(ticks, format);
  const w = Math.max(width, 200);
  const plotW = w - ML - M.right;
  const plotH = height - M.top - M.bottom;
  const x = (i: number) => ML + (n <= 1 ? plotW / 2 : (i * plotW) / (n - 1));
  const y = (v: number) => M.top + plotH - (v / top) * plotH;

  const path = (values: (number | null)[]) => {
    let d = '';
    let pen = false;
    values.forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const onMove = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left - ML;
    setActive(Math.max(0, Math.min(n - 1, Math.round(n <= 1 ? 0 : (px / plotW) * (n - 1)))));
  };
  const lastIndex = (values: (number | null)[]) => {
    for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return i;
    return -1;
  };

  return (
    <Box ref={ref} pos="relative">
      {series.length > 1 && <Legend items={series.map((s) => ({ label: s.label, tone: s.tone }))} />}
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${w} ${height}`}
        role="img"
        aria-label={ariaLabel}
        tabIndex={0}
        style={{ display: 'block', outline: 'none', touchAction: 'pan-y' }}
        onPointerMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setActive(null)}
        onKeyDown={keyboardHandler(n, setActive, active)}
        onBlur={() => setActive(null)}
      >
        {ticks.map((tv) => (
          <g key={tv}>
            <line x1={ML} x2={w - M.right} y1={y(tv)} y2={y(tv)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={ML - 8} y={y(tv)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--mantine-color-dimmed)" className="hms-num">
              {format(tv)}
            </text>
          </g>
        ))}
        {xLabelIndexes(n, plotW).map((i) => (
          <text key={i} x={x(i)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--mantine-color-dimmed)">
            {labels[i]}
          </text>
        ))}
        {area && series[0] && (
          <path
            d={`${path(series[0].values)}L${x(lastIndex(series[0].values))},${y(0)}L${x(series[0].values.findIndex((v) => v !== null))},${y(0)}Z`}
            fill={COLOR[series[0].tone]}
            opacity={0.1}
          />
        )}
        {[...series].reverse().map((s) => (
          <path key={s.label} d={path(s.values)} fill="none" stroke={COLOR[s.tone]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.map((s) => {
          const i = lastIndex(s.values);
          return i < 0 || active !== null ? null : (
            <circle key={s.label} cx={x(i)} cy={y(s.values[i] as number)} r={4} fill={COLOR[s.tone]} stroke="var(--viz-surface)" strokeWidth={2} />
          );
        })}
        {active !== null && (
          <g>
            <line x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} stroke="var(--mantine-color-dimmed)" strokeWidth={1} />
            {series.map((s) =>
              s.values[active] === null ? null : (
                <circle key={s.label} cx={x(active)} cy={y(s.values[active] as number)} r={4} fill={COLOR[s.tone]} stroke="var(--viz-surface)" strokeWidth={2} />
              ),
            )}
          </g>
        )}
      </svg>
      {active !== null && (
        <Tooltip
          x={x(active)}
          width={w}
          top={series.length > 1 ? 30 : 4}
          title={titles[active]}
          rows={series.map((s) => ({ label: s.label, tone: s.tone, value: s.values[active] === null ? '—' : format(s.values[active] as number) }))}
        />
      )}
    </Box>
  );
}

export interface ColumnSeries {
  label: string;
  tone: Tone;
  values: number[];
}

/** Columns, optionally stacked (series bottom to top), one per x position. */
export function ColumnChart({
  labels,
  titles,
  series,
  format,
  height = 200,
  yMax,
  ariaLabel,
  footer,
}: {
  labels: string[];
  titles: string[];
  series: ColumnSeries[];
  format: (v: number) => string;
  height?: number;
  yMax?: number;
  ariaLabel: string;
  footer?: (i: number) => { label: string; value: string } | null;
}) {
  const { ref, width } = useElementSize();
  const [active, setActive] = useState<number | null>(null);
  const n = labels.length;
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));
  const ticks = niceTicks(yMax ?? Math.max(0, ...totals));
  const top = ticks[ticks.length - 1] || 1;
  const ML = leftMargin(ticks, format);
  const w = Math.max(width, 200);
  const plotW = w - ML - M.right;
  const plotH = height - M.top - M.bottom;
  const band = plotW / Math.max(n, 1);
  const barW = Math.max(2, Math.min(24, band * 0.62));
  const y = (v: number) => M.top + plotH - (v / top) * plotH;
  const cx = (i: number) => ML + band * i + band / 2;
  const GAP = 2;

  return (
    <Box ref={ref} pos="relative">
      {series.length > 1 && <Legend shape="rect" items={series.map((s) => ({ label: s.label, tone: s.tone }))} />}
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${w} ${height}`}
        role="img"
        aria-label={ariaLabel}
        tabIndex={0}
        style={{ display: 'block', outline: 'none', touchAction: 'pan-y' }}
        onPointerLeave={() => setActive(null)}
        onKeyDown={keyboardHandler(n, setActive, active)}
        onBlur={() => setActive(null)}
      >
        {ticks.map((tv) => (
          <g key={tv}>
            <line x1={ML} x2={w - M.right} y1={y(tv)} y2={y(tv)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={ML - 8} y={y(tv)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--mantine-color-dimmed)" className="hms-num">
              {format(tv)}
            </text>
          </g>
        ))}
        {xLabelIndexes(n, plotW).map((i) => (
          <text key={i} x={cx(i)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--mantine-color-dimmed)">
            {labels[i]}
          </text>
        ))}
        {labels.map((_, i) => {
          let base = 0;
          const segments = series
            .map((s, si) => ({ s, si, v: s.values[i] ?? 0 }))
            .filter((seg) => seg.v > 0);
          return (
            <g key={i} opacity={active === null || active === i ? 1 : 0.55}>
              {segments.map((seg, k) => {
                const y0 = y(base);
                base += seg.v;
                const y1 = y(base);
                const isTop = k === segments.length - 1;
                const h = Math.max(0, y0 - y1 - (k > 0 ? GAP : 0));
                const x0 = cx(i) - barW / 2;
                const yTop = y1;
                const r = isTop ? Math.min(4, h, barW / 2) : 0;
                // Square at the baseline, rounded data end on the top segment.
                const d = `M${x0},${yTop + h}V${yTop + r}${r ? `Q${x0},${yTop} ${x0 + r},${yTop}` : ''}H${x0 + barW - r}${r ? `Q${x0 + barW},${yTop} ${x0 + barW},${yTop + r}` : ''}V${yTop + h}Z`;
                return <path key={seg.si} d={d} fill={COLOR[seg.s.tone]} />;
              })}
              <rect
                x={ML + band * i}
                y={M.top}
                width={band}
                height={plotH}
                fill="transparent"
                onPointerEnter={() => setActive(i)}
                onPointerDown={() => setActive(i)}
              />
            </g>
          );
        })}
      </svg>
      {active !== null && (
        <Tooltip
          x={cx(active)}
          width={w}
          top={series.length > 1 ? 30 : 4}
          title={titles[active]}
          rows={[
            ...[...series].reverse().map((s) => ({ label: s.label, tone: s.tone, value: format(s.values[active] ?? 0) })),
            ...(footer?.(active) ? [footer(active) as { label: string; value: string }] : []),
          ]}
        />
      )}
    </Box>
  );
}

/** A ratio against its whole, on a lighter track of the same hue. */
export function Meter({ value, max = 100, label }: { value: number | null; max?: number; label: string }) {
  const share = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  return (
    <div role="meter" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={max} aria-label={label} style={{ height: 8, borderRadius: 4, background: 'var(--viz-track)', overflow: 'hidden', minWidth: 60 }}>
      <div style={{ width: `${share * 100}%`, height: '100%', borderRadius: 4, background: 'var(--viz-accent)' }} />
    </div>
  );
}

export function ChartCard({ title, subtitle, children, actions }: { title: string; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <Paper withBorder radius="md" p="md" style={{ background: 'var(--viz-surface)' }}>
      <Group justify="space-between" align="flex-start" mb="xs" wrap="nowrap">
        <div>
          <Text fw={600}>{title}</Text>
          {subtitle && (
            <Text size="xs" c="dimmed">
              {subtitle}
            </Text>
          )}
        </div>
        {actions}
      </Group>
      {children}
    </Paper>
  );
}
