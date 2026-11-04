/**
 * The Display tab's daily cost stacked by campaign (Stitch 56a8ea4c), over every day of the range: a day the backend
 * covered (`daily`) and a campaign had no row is zero; a day never fetched is a gap, never drawn as zero spend.
 */
import { formatSignedMoney } from '../utils/ventasMlTone';
import { campaignName, daysOf, formatDate, formatShortMoney } from '../utils/displayAds';
import styles from './DisplayAdsML.module.css';

// Series colors in the order of the Stitch legend (blue, indigo, teal, amber), then green and gray for the 5th and
// 6th campaign (orchestrator, 2026-11-04). A 7th starts the palette again.
const SERIES = ['s0', 's1', 's2', 's3', 's4', 's5'];
const seriesClass = (index) => styles[SERIES[index % SERIES.length]];

// `left` is the y-axis gutter in viewBox units; the axis labels get the same share of the width (`--gutter`).
const STACK = { width: 1000, height: 220, left: 64, bottom: 8, top: 8 };
const GUTTER = `${(STACK.left / STACK.width) * 100}%`;

/** The niceness of the axis: the top tick is the max rounded up to 1, 2 or 5 times a power of ten. */
function niceTop(max) {
  if (max <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(max));
  return [1, 2, 5, 10].map((f) => f * power).find((v) => v >= max);
}

export function StackedDailyCost({ campaigns, daily, range }) {
  const covered = new Set(daily.map((d) => d.day));
  const days = daysOf(range.from, range.to);
  const spent = campaigns.filter((c) => c.cost > 0);
  const costOf = spent.map((c) => new Map(c.days.map((d) => [d.day, d.cost])));
  const totals = days.map((day) => (covered.has(day) ? costOf.reduce((sum, m) => sum + (m.get(day) || 0), 0) : null));
  const top = niceTop(Math.max(0, ...totals.filter((v) => v !== null)));
  const plotHeight = STACK.height - STACK.top - STACK.bottom;
  const slot = (STACK.width - STACK.left) / Math.max(days.length, 1);
  const barWidth = Math.max(slot * 0.62, 1);
  const toY = (v) => STACK.top + plotHeight - (v / top) * plotHeight;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const dayTicks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (days.length - 1))))];
  const known = totals.filter((v) => v !== null).length;

  return (
    <section className={styles.chartCard} aria-label="Costo diario por campaña">
      <div className={styles.chartHeader}>
        <div>
          <h3 className={styles.cardTitle}>Costo diario por campaña</h3>
          <span className={styles.cardSub}>
            {formatDate(range.from)} a {formatDate(range.to)} ({days.length} {days.length === 1 ? 'día' : 'días'})
          </span>
        </div>
        <ul className={styles.legend}>
          {spent.map((c, i) => (
            <li key={`${c.advertiser_id}-${c.campaign_id}`} className={styles.legendItem}>
              <span className={`${styles.swatch} ${seriesClass(i)}`} aria-hidden="true" />
              <span>{campaignName(c)}</span>
              <span className={styles.legendValue}>({formatShortMoney(c.cost)})</span>
            </li>
          ))}
        </ul>
      </div>
      {known === 0 ? (
        <p className={styles.chartEmpty}>Sin días guardados en el rango.</p>
      ) : (
        <>
          <div className={styles.plot} style={{ '--gutter': GUTTER }}>
            <svg
              className={styles.stack}
              viewBox={`0 0 ${STACK.width} ${STACK.height}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={`Costo diario por campaña, ${known} de ${days.length} días con datos`}
            >
              {ticks.map((v) => (
                <line key={v} className={styles.grid} x1={STACK.left} x2={STACK.width} y1={toY(v)} y2={toY(v)} />
              ))}
              {days.map((day, i) => {
                if (totals[i] === null) return null;
                const x = STACK.left + i * slot + (slot - barWidth) / 2;
                let base = 0;
                return (
                  <g key={day}>
                    {costOf.map((m, s) => {
                      const cost = m.get(day) || 0;
                      if (!cost) return null;
                      const y = toY(base + cost);
                      const height = toY(base) - y;
                      base += cost;
                      return (
                        <rect key={s} className={seriesClass(s)} x={x} y={y} width={barWidth} height={height}>
                          <title>{`${formatDate(day)} · ${campaignName(spent[s])}: ${formatSignedMoney(cost)}`}</title>
                        </rect>
                      );
                    })}
                  </g>
                );
              })}
            </svg>
            <div className={styles.yAxis} aria-hidden="true">
              {[...ticks].reverse().map((v) => (
                <span key={v}>{formatShortMoney(v)}</span>
              ))}
            </div>
          </div>
          <div className={styles.axis} style={{ '--gutter': GUTTER }} aria-hidden="true">
            {dayTicks.map((i) => (
              <span key={i}>{formatDate(days[i]).slice(0, 5)}</span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

