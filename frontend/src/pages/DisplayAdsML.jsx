/**
 * DisplayAdsML — the Display tab of ML Ads (ml-ads-cupones-display S8).
 *
 * Every Display campaign over a date range (`GET /ml-ads/display`, `ml_metricas.ver_ganancia`): its catalog (name,
 * goal, status, dates), cost, prints, clicks, reach, the sales Mercado Libre attributes to it, and CTR/CPC/CPM/ROAS
 * as the backend computes them (null without a base, shown "—", never 0). KPI tiles sum the period; the daily cost
 * is drawn over the range (a day Display closed without activity is zero; one never fetched is a gap); the toolbar
 * filters the loaded rows.
 *
 * Layout from the Stitch screen "ML Ads - Display (Campaña y Rendimiento)", with the shell and tokens of Aportes.
 * Reach, like every figure, is the sum of each day's (ML gives no unique reach over a range): one person reached on
 * two days, or by two campaigns, counts twice. The column says so.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AlertTriangle, Info, Search } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import { SegmentedControl, StatusPill } from '../components/kit';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import { formatSignedMoney } from '../utils/ventasMlTone';
import shell from './AportesAdsML.module.css';
import styles from './DisplayAdsML.module.css';

const STATUS_PILLS = { active: { text: 'Activa', tone: 'success' }, paused: { text: 'Pausada', tone: 'neutral' } };
const GOALS = { conversion: 'Conversión', consideration: 'Consideración', awareness: 'Alcance' };
const COLUMNS = 15;

const INT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
const RATIO = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const formatDate = (iso) => {
  if (!iso) return '—';
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year}`;
};

const formatInt = (value) => INT.format(value || 0);
const formatCtr = (value) => (value === null || value === undefined ? '—' : `${RATIO.format(value * 100)} %`);
const formatRoas = (value) => (value === null || value === undefined ? '—' : RATIO.format(value));
const formatRatioMoney = (value) => (value === null || value === undefined ? '—' : formatSignedMoney(value));

const SUMMED = ['cost', 'prints', 'clicks', 'reach', 'attributed_amount', 'attributed_units'];

/** The visible rows' sums with their ratios recomputed the backend's way (ratios never add up). */
function totalsOf(rows) {
  const t = Object.fromEntries(SUMMED.map((key) => [key, rows.reduce((sum, row) => sum + (row[key] || 0), 0)]));
  return {
    ...t,
    ctr: t.prints ? t.clicks / t.prints : null,
    cpc: t.clicks ? t.cost / t.clicks : null,
    cpm: t.prints ? (t.cost * 1000) / t.prints : null,
    roas: t.cost ? t.attributed_amount / t.cost : null,
  };
}

// The API accepts at most 366 calendar days, both ends included (`MAX_DAYS` in routers/ml_ads.py).
const MAX_DAYS = 366;

/** Every day of the range, ISO, both ends included. */
function daysOf(from, to) {
  const days = [];
  const cursor = new Date(`${from}T12:00:00`);
  const end = new Date(`${to}T12:00:00`);
  while (cursor <= end && days.length < MAX_DAYS) {
    days.push(isoDay(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return days;
}

const CHART = { width: 1000, height: 160, pad: 8 };

function DailyCost({ daily, range }) {
  const byDay = new Map(daily.map((d) => [d.day, d.cost]));
  const days = daysOf(range.from, range.to);
  const values = days.map((day) => (byDay.has(day) ? byDay.get(day) : null));
  const known = values.filter((v) => v !== null);
  const max = Math.max(...known, 0) || 1;
  const stepX = days.length > 1 ? (CHART.width - CHART.pad * 2) / (days.length - 1) : 0;
  const toX = (i) => CHART.pad + i * stepX;
  const toY = (v) => CHART.height - CHART.pad - (v / max) * (CHART.height - CHART.pad * 2);
  // One path per run of known days: a missing day breaks the line instead of being drawn as zero.
  const runs = [];
  values.forEach((v, i) => {
    if (v === null) return;
    if (i === 0 || values[i - 1] === null) runs.push([]);
    runs[runs.length - 1].push([toX(i), toY(v)]);
  });
  const average = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  const ticks = [...new Set([0, Math.floor((days.length - 1) / 2), days.length - 1])];

  return (
    <section className={styles.chartCard} aria-label="Costo diario">
      <div className={styles.chartHeader}>
        <span className={shell.kpiLabel}>
          Costo diario ({formatDate(range.from)} a {formatDate(range.to)})
        </span>
        <span className={styles.chartAverage}>
          {average === null ? 'Sin días guardados' : `Promedio: ${formatSignedMoney(average)}/día`}
        </span>
      </div>
      <svg
        className={styles.chart}
        viewBox={`0 0 ${CHART.width} ${CHART.height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Costo diario de Display, ${known.length} de ${days.length} días con datos`}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} className={styles.grid} x1="0" x2={CHART.width} y1={CHART.height * f} y2={CHART.height * f} />
        ))}
        {runs.map((run) => {
          const line = run.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
          const base = CHART.height - CHART.pad;
          return (
            <g key={run[0][0]}>
              <path
                className={styles.area}
                d={`${line} L${run[run.length - 1][0].toFixed(1)} ${base} L${run[0][0].toFixed(1)} ${base} Z`}
              />
              <path className={styles.line} d={line} vectorEffect="non-scaling-stroke" />
              {run.length === 1 && <circle className={styles.dot} cx={run[0][0]} cy={run[0][1]} r="4" />}
            </g>
          );
        })}
      </svg>
      <div className={styles.axis}>
        {ticks.map((i) => (
          <span key={i}>{formatDate(days[i]).slice(0, 5)}</span>
        ))}
      </div>
    </section>
  );
}

export default function DisplayAdsML() {
  const { tienePermiso } = usePermisos();
  const puedeVerGanancia = tienePermiso('ml_metricas.ver_ganancia');
  const today = new Date();
  const [range, setRange] = useState({
    from: isoDay(new Date(today.getFullYear(), today.getMonth(), 1)),
    to: isoDay(today),
  });
  const [report, setReport] = useState(null);
  const [search, setSearch] = useState('');
  const [segment, setSegment] = useState('all');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  // Only the newest request may write the report: a range changed quickly must not be overwritten by a slower one.
  const latestRequest = useRef(0);

  const fetchReport = useCallback(async () => {
    const request = ++latestRequest.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { data } = await api.get('/ml-ads/display', { params: { date_from: range.from, date_to: range.to } });
      if (request === latestRequest.current) setReport(data ? { ...data, range: { ...range } } : null);
    } catch (err) {
      if (request !== latestRequest.current) return;
      setReport(null);
      setLoadError(apiErrorMessage(err, 'No se pudo cargar Display'));
    } finally {
      if (request === latestRequest.current) setLoading(false);
    }
  }, [range]);

  const rangoValido = Boolean(range.from && range.to && range.from <= range.to);

  useEffect(() => {
    if (puedeVerGanancia && rangoValido) fetchReport();
  }, [fetchReport, puedeVerGanancia, rangoValido]);

  if (!puedeVerGanancia) {
    return (
      <div className={shell.container}>
        <div className={shell.alertError} role="alert">
          <AlertTriangle size={16} /> Necesitás el permiso para ver la ganancia de Métricas ML para ver Display.
        </div>
      </div>
    );
  }

  // An invalid range asks for nothing, and the last report (of another range) is not shown as if it were this one.
  const shown = rangoValido ? report : null;
  const campaigns = shown?.campaigns ?? [];
  const count = (status) => campaigns.filter((c) => c.status === status).length;
  const segments = [
    { value: 'all', label: `Todas ${campaigns.length}` },
    { value: 'active', label: `Activas ${count('active')}` },
    { value: 'paused', label: `Pausadas ${count('paused')}` },
  ];
  const needle = search.trim().toLowerCase();
  const visible = campaigns.filter(
    (c) =>
      (!needle || (c.name || '').toLowerCase().includes(needle) || String(c.campaign_id).includes(needle)) &&
      (segment === 'all' || c.status === segment),
  );
  const totals = totalsOf(visible);
  const period = shown?.totals;
  const show = (render) => (loading || !period ? '—' : render(period));
  // Coverage lists one row per advertiser and day; the notice counts days.
  const missing = new Set((shown?.coverage?.missing_days ?? []).filter((d) => d.source === 'display').map((d) => d.day))
    .size;

  return (
    <div className={shell.container}>
      <header className={shell.header}>
        <div>
          <h2 className={shell.title}>Display</h2>
          <p className={shell.description}>
            Campañas de Display de Mercado Libre: costo, rendimiento y ventas atribuidas en el período.
          </p>
        </div>
        <div className={shell.headerActions}>
          <div className={shell.range}>
            <label className={shell.rangeField}>
              <span>Desde</span>
              <input
                type="date"
                className={shell.rangeInput}
                value={range.from}
                onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
              />
            </label>
            <label className={shell.rangeField}>
              <span>Hasta</span>
              <input
                type="date"
                className={shell.rangeInput}
                value={range.to}
                onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
              />
            </label>
          </div>
        </div>
      </header>

      <section className={`${shell.kpis} ${styles.kpis}`} aria-label="Resumen de Display">
        <div className={shell.kpi}>
          <span className={shell.kpiLabel}>Costo</span>
          <span className={shell.kpiValue}>{show((p) => formatSignedMoney(p.cost))}</span>
          <span className={shell.kpiSub}>Sin IVA, como lo informa Mercado Libre</span>
        </div>
        <div className={shell.kpi}>
          <span className={shell.kpiLabel}>Impresiones</span>
          <span className={shell.kpiValue}>{show((p) => formatInt(p.prints))}</span>
          <span className={shell.kpiSub}>{show((p) => `CPM ${formatRatioMoney(p.cpm)}`)}</span>
        </div>
        <div className={shell.kpi}>
          <span className={shell.kpiLabel}>Clics</span>
          <span className={shell.kpiValue}>{show((p) => formatInt(p.clicks))}</span>
          <span className={shell.kpiSub}>{show((p) => `CTR ${formatCtr(p.ctr)}`)}</span>
        </div>
        <div className={shell.kpi}>
          <span className={shell.kpiLabel}>Ventas atribuidas</span>
          <span className={`${shell.kpiValue} ${shell.positive}`}>
            {show((p) => formatSignedMoney(p.attributed_amount))}
          </span>
          <span className={shell.kpiSub}>{show((p) => `${formatInt(p.attributed_units)} unid.`)}</span>
        </div>
        <div className={shell.kpi}>
          <span className={shell.kpiLabel}>ROAS</span>
          <span className={shell.kpiValue}>{show((p) => formatRoas(p.roas))}</span>
          <span className={shell.kpiSub}>Ventas atribuidas / costo</span>
        </div>
      </section>

      {shown && <DailyCost daily={shown.daily} range={shown.range} />}

      <div className={shell.toolbar}>
        <label className={shell.search}>
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            className={shell.searchInput}
            aria-label="Buscar campaña"
            placeholder="Buscar campaña o ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <SegmentedControl label="Estado" options={segments} value={segment} onChange={setSegment} />
        <span className={styles.count}>
          {campaigns.length} {campaigns.length === 1 ? 'campaña' : 'campañas'} en total
        </span>
      </div>

      {!rangoValido && (
        <div className={shell.alertError} role="alert">
          <AlertTriangle size={16} /> Elegí un rango válido: Desde tiene que ser anterior o igual a Hasta.
        </div>
      )}
      {loadError && (
        <div className={shell.alertError} role="alert">
          <AlertTriangle size={16} /> {loadError}
        </div>
      )}
      {missing > 0 && (
        <p className={shell.footnote}>
          <AlertTriangle size={14} aria-hidden="true" /> Faltan {missing} {missing === 1 ? 'día' : 'días'} de Display
          sin guardar en el rango: las cifras pueden estar incompletas.
        </p>
      )}

      <div className={shell.tableCard}>
        <table className={shell.table}>
          <thead>
            <tr>
              <th>Campaña</th>
              <th>Objetivo</th>
              <th>Estado</th>
              <th>Desde</th>
              <th>Hasta</th>
              <th className={shell.num}>Costo</th>
              <th className={shell.num}>Impresiones</th>
              <th className={shell.num}>Clics</th>
              <th className={shell.num} title="Suma del alcance de cada día: una persona alcanzada dos días cuenta dos veces">
                Alcance
              </th>
              <th className={shell.num}>CTR</th>
              <th className={shell.num}>CPC</th>
              <th className={shell.num}>CPM</th>
              <th className={shell.num}>Ventas atribuidas</th>
              <th className={shell.num}>Unidades</th>
              <th className={shell.num}>ROAS</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={COLUMNS} className={shell.muted}>Cargando...</td>
              </tr>
            )}
            {!loading && campaigns.length > 0 && visible.length === 0 && (
              <tr>
                <td colSpan={COLUMNS} className={shell.muted}>Ninguna campaña coincide con los filtros.</td>
              </tr>
            )}
            {!loading && rangoValido && campaigns.length === 0 && !loadError && (
              <tr>
                <td colSpan={COLUMNS} className={shell.muted}>Todavía no hay campañas de Display sincronizadas.</td>
              </tr>
            )}
            {!loading &&
              visible.map((c) => {
                const status = STATUS_PILLS[c.status];
                const idle = !c.cost && !c.prints;
                return (
                  <tr key={`${c.advertiser_id}-${c.campaign_id}`} className={idle ? styles.idle : undefined}>
                    <td>
                      <div className={styles.campaign}>
                        <span className={shell.campaignName}>{c.name || `Campaña ${c.campaign_id}`}</span>
                        <span className={shell.campaignId}>ID {c.campaign_id}</span>
                      </div>
                    </td>
                    <td className={styles.nowrap}>{GOALS[c.goal] || c.goal || '—'}</td>
                    <td>
                      {status ? (
                        <span className={shell.keep}>
                          <StatusPill tone={status.tone} dot>
                            {status.text}
                          </StatusPill>
                        </span>
                      ) : (
                        <span className={shell.muted}>{c.status || '—'}</span>
                      )}
                    </td>
                    <td className={styles.date}>{formatDate(c.start_date)}</td>
                    <td className={styles.date}>{formatDate(c.end_date)}</td>
                    <td className={shell.num}>{formatSignedMoney(c.cost)}</td>
                    <td className={shell.num}>{formatInt(c.prints)}</td>
                    <td className={shell.num}>{formatInt(c.clicks)}</td>
                    <td className={shell.num}>{formatInt(c.reach)}</td>
                    <td className={shell.num}>{formatCtr(c.ctr)}</td>
                    <td className={shell.num}>{formatRatioMoney(c.cpc)}</td>
                    <td className={shell.num}>{formatRatioMoney(c.cpm)}</td>
                    <td className={shell.num}>{formatSignedMoney(c.attributed_amount)}</td>
                    <td className={shell.num}>{formatInt(c.attributed_units)}</td>
                    <td className={shell.num}>{formatRoas(c.roas)}</td>
                  </tr>
                );
              })}
          </tbody>
          {!loading && visible.length > 0 && (
            <tfoot>
              <tr>
                <td>Total</td>
                <td colSpan={4} className={shell.muted}>
                  {visible.length} {visible.length === 1 ? 'campaña' : 'campañas'}
                </td>
                <td className={shell.num}>{formatSignedMoney(totals.cost)}</td>
                <td className={shell.num}>{formatInt(totals.prints)}</td>
                <td className={shell.num}>{formatInt(totals.clicks)}</td>
                <td className={shell.num}>{formatInt(totals.reach)}</td>
                <td className={shell.num}>{formatCtr(totals.ctr)}</td>
                <td className={shell.num}>{formatRatioMoney(totals.cpc)}</td>
                <td className={shell.num}>{formatRatioMoney(totals.cpm)}</td>
                <td className={shell.num}>{formatSignedMoney(totals.attributed_amount)}</td>
                <td className={shell.num}>{formatInt(totals.attributed_units)}</td>
                <td className={shell.num}>{formatRoas(totals.roas)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className={shell.footnote}>
        <Info size={14} aria-hidden="true" /> Costo sin IVA, como lo informa Mercado Libre. Ventas atribuidas por
        Mercado Libre a la fecha del evento. Display se guarda a diario: Mercado Libre solo conserva 90 días.
      </p>
    </div>
  );
}
