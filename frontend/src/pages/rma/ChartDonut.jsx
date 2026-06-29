/**
 * ChartDonut.jsx
 *
 * Recharts-based donut chart for a single RMA metric dimension.
 *
 * IMPORTANT: This is the ONLY file in the codebase that imports from recharts.
 * All recharts imports must stay here to keep the code-split boundary clean
 * (recharts ~100kb gz lands only in the lazy-loaded Metricas chunk, never in
 * the main bundle).
 *
 * Props:
 *   title          {string}    Human-readable dimension label.
 *   buckets        {Array}     BucketOut[]: { id, valor, color, cantidad }.
 *   onSegmentClick {Function}  Called with the BucketOut when a segment is clicked.
 */
import { memo } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { getColorForBucket, SEGMENT_LABEL_COLOR } from './metricsColors';
import styles from './ChartDonut.module.css';

const RADIAN = Math.PI / 180;

function PercentLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  if (percent < 0.06) return null;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text
      x={x}
      y={y}
      fill={SEGMENT_LABEL_COLOR}
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={11}
      fontWeight={600}
    >
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
}

function DonutTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const entry = payload[0];
  return (
    <div className={styles.tooltip}>
      <span
        className={styles.tooltipDot}
        style={{ backgroundColor: entry.payload.fill }}
      />
      <span className={styles.tooltipLabel}>{entry.name}</span>
      <span className={styles.tooltipValue}>
        {entry.value.toLocaleString('es-AR')}
      </span>
    </div>
  );
}

function ChartDonut({ title, buckets = [], onSegmentClick }) {
  const chartData = buckets
    .filter((b) => b.cantidad > 0)
    .map((bucket, index) => ({
      name: bucket.valor,
      value: bucket.cantidad,
      fill: getColorForBucket(bucket, index),
      bucket,
    }));

  const total = buckets.reduce((sum, b) => sum + b.cantidad, 0);

  const handleClick = (entry) => {
    if (onSegmentClick && entry && entry.bucket) {
      onSegmentClick(entry.bucket);
    }
  };

  return (
    <div className={styles.wrapper}>
      <h3 className={styles.title}>{title}</h3>
      {total === 0 ? (
        <div className={styles.empty}>Sin datos en el período</div>
      ) : (
        <>
          <div className={styles.totalBadge}>
            {total.toLocaleString('es-AR')} items
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={52}
                outerRadius={85}
                dataKey="value"
                labelLine={false}
                label={PercentLabel}
                onClick={handleClick}
                style={{ cursor: onSegmentClick ? 'pointer' : 'default' }}
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip content={<DonutTooltip />} />
              <Legend
                formatter={(value) => (
                  <span className={styles.legendLabel}>{value}</span>
                )}
                wrapperStyle={{ fontSize: '11px', paddingTop: '4px' }}
              />
            </PieChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}

// Memo: recharts PieChart is expensive — prevent re-render when parent
// state changes (e.g. drill-down modal open/close) don't affect this chart.
export default memo(ChartDonut);
