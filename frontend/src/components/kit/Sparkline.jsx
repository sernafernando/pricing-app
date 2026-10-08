import styles from './Sparkline.module.css';

/**
 * Inline-SVG sparkline (ODD `metricas-ml-tablero` T4): one line through the
 * KNOWN points of `values`, a dot on the last one, a dashed mid baseline.
 * A `null` is "no data that day" and is skipped, never drawn as zero -- a
 * day without sales has no markup, not a 0% markup. No chart library: fifty
 * rows of these are fifty tiny SVGs, nothing to load.
 *
 * `tone` ('up' | 'down' | 'flat' | null) only picks the colour, through the
 * stylesheet, so both themes keep working.
 */
const PAD = 2;

export default function Sparkline({ values, width = 120, height = 32, tone = null, label, className = '' }) {
  const points = values
    .map((value, index) => (value === null || value === undefined ? null : [index, Number(value)]))
    .filter(Boolean);
  const ys = points.map(([, y]) => y);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const stepX = values.length > 1 ? (width - PAD * 2) / (values.length - 1) : 0;
  const toX = (index) => PAD + index * stepX;
  const toY = (y) => (max === min ? height / 2 : PAD + (1 - (y - min) / span) * (height - PAD * 2));
  const d = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${toX(x).toFixed(1)} ${toY(y).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];

  return (
    <svg
      className={`${styles.spark} ${className}`}
      data-tone={tone || 'none'}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
    >
      <line className={styles.baseline} x1="0" x2={width} y1={height / 2} y2={height / 2} />
      {points.length > 0 && <path className={styles.line} d={d} />}
      {last && <circle className={styles.dot} cx={toX(last[0])} cy={toY(last[1])} r="2.5" />}
    </svg>
  );
}
