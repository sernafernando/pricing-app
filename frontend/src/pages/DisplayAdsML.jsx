/**
 * DisplayAdsML — the Display tab of ML Ads (ml-ads-cupones-display S8), laid out after the approved Stitch screen
 * 56a8ea4c "ML Ads - Display (Back-Office Operativo)".
 *
 * Every Display campaign over a date range (`GET /ml-ads/display`, `ml_metricas.ver_ganancia`): its catalog (name,
 * goal, status, dates), cost, prints, clicks, reach, the sales Mercado Libre attributes to it, and CTR/CPC/CPM/ROAS
 * as the backend computes them (null without a base, shown "—", never 0). A campaign without activity keeps its real
 * zeros. The KPI tiles sum the period; attributed sales are compared with the previous period of the same length
 * only when neither period has Display days missing (otherwise it says why). The daily cost is stacked by campaign,
 * and a row opens its campaign's daily trend, average daily spend (over the days the backend covered) and peak daily
 * ROAS.
 *
 * Reach, like every figure, is the sum of each day's (ML gives no unique reach over a range): one person reached on
 * two days, or by two campaigns, counts twice. The column says so.
 *
 * Inside the ML Ads page the range and Actualizar go to the page header (`headerSlot`), as in the screen; the
 * number of active campaigns is handed to the page (`onActiveCount`) for the tab.
 */
import { useState, useEffect, useCallback, useRef, Fragment } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Banknote,
  Calendar,
  ChevronDown,
  ChevronRight,
  Eye,
  Info,
  RefreshCw,
  Search,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import { SegmentedControl, Sparkline, StatusPill } from '../components/kit';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import { formatSignedMoney } from '../utils/ventasMlTone';
import { StackedDailyCost } from './DisplayAdsMLCharts';
import { campaignDailyCosts, campaignName, daysOf, formatDate, isoDay } from '../utils/displayAds';
import shell from './AportesAdsML.module.css';
import styles from './DisplayAdsML.module.css';

const STATUS_PILLS = { active: { text: 'Activa', tone: 'success' }, paused: { text: 'Pausada', tone: 'neutral' } };
const GOALS = { conversion: 'Conversión', consideration: 'Consideración', awareness: 'Alcance' };
const COLUMNS = 14;

const INT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
const RATIO = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ONE = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const formatInt = (value) => INT.format(value || 0);
const formatCtr = (value) => (value === null || value === undefined ? '—' : `${RATIO.format(value * 100)} %`);
const formatRoas = (value) => (value === null || value === undefined ? '—' : `${ONE.format(value)}x`);
const formatRatioMoney = (value) => (value === null || value === undefined ? '—' : formatSignedMoney(value));
const plural = (n, one, many) => `${formatInt(n)} ${n === 1 ? one : many}`;

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

/** The period of the same length that ends the day before `range` starts. */
function previousOf(range) {
  const length = daysOf(range.from, range.to).length;
  const end = new Date(`${range.from}T12:00:00`);
  end.setDate(end.getDate() - 1);
  const start = new Date(end);
  start.setDate(start.getDate() - (length - 1));
  return { from: isoDay(start), to: isoDay(end) };
}

/** Display days missing from a report's coverage (one row per advertiser and day; this counts days). */
const missingDays = (report) =>
  new Set((report?.coverage?.missing_days ?? []).filter((d) => d.source === 'display').map((d) => d.day)).size;

/** The attributed-sales change against the previous period, or why there is none. */
function comparisonOf(report, previous) {
  if (!report || !previous) return null;
  // A gap in either period would compare incomplete figures. The chosen period's own gap is named first, since it
  // also shows as the missing-days warning; otherwise the previous period's.
  const own = missingDays(report);
  const prior = missingDays(previous);
  if (own > 0 || prior > 0) {
    const where = own > 0 ? 'del período' : 'del período anterior';
    return { text: `Sin comparación: faltan ${plural(own || prior, 'día', 'días')} ${where}`, tone: 'neutral' };
  }
  const before = previous.totals?.attributed_amount;
  // No sales in the previous period: a percentage over zero has no base, so nothing is shown.
  if (!before) return null;
  const change = (report.totals.attributed_amount - before) / before;
  return {
    text: `${change >= 0 ? '+' : ''}${ONE.format(change * 100)} % vs per. ant.`,
    tone: change >= 0 ? 'up' : 'down',
  };
}

/** A campaign's trend: its average daily spend over the covered days and its best day by ROAS. */
function trendOf(campaign, report) {
  const covered = report.daily.length;
  const average = covered ? campaign.days.reduce((sum, d) => sum + d.cost, 0) / covered : null;
  let peak = null;
  for (const d of campaign.days) {
    if (d.cost > 0 && (peak === null || d.attributed_amount / d.cost > peak.roas)) {
      peak = { roas: d.attributed_amount / d.cost, day: d.day };
    }
  }
  return { average, peak };
}

function TrendRow({ campaign, report }) {
  const name = campaignName(campaign);
  const { average, peak } = trendOf(campaign, report);
  const days = daysOf(report.range.from, report.range.to).length;
  return (
    <tr className={styles.trendRow}>
      <td colSpan={COLUMNS}>
        <section className={styles.trend} aria-label={`Tendencia diaria de ${name}`}>
          <div className={styles.trendText}>
            <span className={styles.trendTitle}>
              <span className={styles.trendDot} aria-hidden="true" />
              Desglose de tendencia diaria: {name}
            </span>
            {campaign.days.length === 0 ? (
              <span className={styles.trendFigures}>Sin actividad en el período.</span>
            ) : (
              <span className={styles.trendFigures}>
                Inversión promedio diaria:{' '}
                <strong className={styles.mono}>{`${formatSignedMoney(average)}/día`}</strong> · Retorno diario pico:{' '}
                <strong className={`${styles.mono} ${styles.good}`}>
                  {peak ? `${formatRoas(peak.roas)} (${formatDate(peak.day).slice(0, 5)})` : '—'}
                </strong>
              </span>
            )}
          </div>
          <div className={styles.trendSpark}>
            <span className={styles.trendDays}>{plural(days, 'día', 'días')}</span>
            <Sparkline
              values={campaignDailyCosts(campaign, report.daily, report.range)}
              width={240}
              height={36}
              label={`Costo diario de ${name}`}
            />
          </div>
        </section>
      </td>
    </tr>
  );
}

export default function DisplayAdsML({ headerSlot = null, onActiveCount }) {
  const { tienePermiso } = usePermisos();
  const puedeVerGanancia = tienePermiso('ml_metricas.ver_ganancia');
  const today = new Date();
  const [range, setRange] = useState({
    from: isoDay(new Date(today.getFullYear(), today.getMonth(), 1)),
    to: isoDay(today),
  });
  const [report, setReport] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [search, setSearch] = useState('');
  const [segment, setSegment] = useState('all');
  const [open, setOpen] = useState(() => new Set());
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  // Only the newest request may write the report: a range changed quickly must not be overwritten by a slower one.
  const latestRequest = useRef(0);

  const fetchReport = useCallback(async () => {
    const request = ++latestRequest.current;
    setLoading(true);
    setLoadError(null);
    const before = previousOf(range);
    // The previous period only feeds the comparison: if it fails, the comparison is left out, never the page.
    const previousRequest = api
      .get('/ml-ads/display', { params: { date_from: before.from, date_to: before.to } })
      .then(({ data }) => data)
      .catch(() => null);
    try {
      const { data } = await api.get('/ml-ads/display', { params: { date_from: range.from, date_to: range.to } });
      const prior = await previousRequest;
      if (request !== latestRequest.current) return;
      setReport(data ? { ...data, range: { ...range } } : null);
      setPrevious(prior);
    } catch (err) {
      if (request !== latestRequest.current) return;
      setReport(null);
      setPrevious(null);
      setLoadError(apiErrorMessage(err, 'No se pudo cargar Display'));
    } finally {
      if (request === latestRequest.current) setLoading(false);
    }
  }, [range]);

  const rangoValido = Boolean(range.from && range.to && range.from <= range.to);

  useEffect(() => {
    if (puedeVerGanancia && rangoValido) fetchReport();
  }, [fetchReport, puedeVerGanancia, rangoValido]);

  // An invalid range asks for nothing, and the last report (of another range) is not shown as if it were this one.
  const shown = rangoValido ? report : null;
  const campaigns = shown?.campaigns ?? [];
  const count = (status) => campaigns.filter((c) => c.status === status).length;
  const active = shown ? count('active') : null;

  // Without current figures (an invalid range, a failed load) the count is cleared, so the tab never keeps a stale one.
  useEffect(() => {
    onActiveCount?.(active);
  }, [active, onActiveCount]);

  if (!puedeVerGanancia) {
    return (
      <div className={shell.container}>
        <div className={shell.alertError} role="alert">
          <AlertTriangle size={16} /> Necesitás el permiso para ver la ganancia de Métricas ML para ver Display.
        </div>
      </div>
    );
  }

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
  const missing = missingDays(shown);
  const comparison = loading ? null : comparisonOf(shown, previous);
  const rangeDays = rangoValido ? daysOf(range.from, range.to).length : null;
  const daysChip = rangeDays === null ? null : plural(rangeDays, 'día', 'días');
  const keyOf = (c) => `${c.advertiser_id}-${c.campaign_id}`;
  const toggle = (key) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const controls = (
    <div className={styles.controls}>
      <div className={styles.rangeBox}>
        <Calendar size={14} aria-hidden="true" />
        <label className={styles.rangeField}>
          <span>Desde</span>
          <input
            type="date"
            className={styles.rangeInput}
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
          />
        </label>
        <span className={styles.rangeDash} aria-hidden="true">
          —
        </span>
        <label className={styles.rangeField}>
          <span>Hasta</span>
          <input
            type="date"
            className={styles.rangeInput}
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
          />
        </label>
        {daysChip && <span className={styles.rangeDays}>{daysChip}</span>}
      </div>
      <button type="button" className={styles.refresh} onClick={fetchReport} disabled={!rangoValido || loading}>
        <RefreshCw size={14} aria-hidden="true" /> Actualizar
      </button>
    </div>
  );

  return (
    <div className={shell.container}>
      {headerSlot ? createPortal(controls, headerSlot) : controls}

      <section className={`${shell.kpis} ${styles.kpis}`} aria-label="Resumen de Display">
        <div className={shell.kpi}>
          <span className={styles.kpiHead}>
            <span className={shell.kpiLabel}>Costo Display</span>
            <Banknote size={16} aria-hidden="true" />
          </span>
          <span className={shell.kpiValue}>{show((p) => formatSignedMoney(p.cost))}</span>
          <span className={styles.kpiFoot}>
            <span className={shell.kpiSub}>Inversión neta (sin IVA)</span>
            {daysChip && <span className={styles.chip}>{daysChip}</span>}
          </span>
        </div>
        <div className={shell.kpi}>
          <span className={styles.kpiHead}>
            <span className={shell.kpiLabel}>Ventas atribuidas</span>
            <TrendingUp size={16} aria-hidden="true" />
          </span>
          <span className={shell.kpiValue}>{show((p) => formatSignedMoney(p.attributed_amount))}</span>
          <span className={styles.kpiFoot}>
            <span className={shell.kpiSub}>
              {show((p) => plural(p.attributed_units, 'unidad vendida', 'unidades vendidas'))}
            </span>
            {comparison && (
              <span className={`${styles.chip} ${styles[comparison.tone]}`}>{comparison.text}</span>
            )}
          </span>
        </div>
        <div className={shell.kpi}>
          <span className={styles.kpiHead}>
            <span className={shell.kpiLabel}>ROAS consolidado</span>
            <Zap size={16} aria-hidden="true" />
          </span>
          <span className={styles.kpiValueRow}>
            <span className={`${shell.kpiValue} ${styles.good}`}>{show((p) => formatRoas(p.roas))}</span>
            <span className={shell.kpiSub}>(Retorno s/ Inversión)</span>
          </span>
          <span className={shell.kpiSub}>Ventas / Costo Display</span>
        </div>
        <div className={shell.kpi}>
          <span className={styles.kpiHead}>
            <span className={shell.kpiLabel}>Impresiones &amp; clics</span>
            <Eye size={16} aria-hidden="true" />
          </span>
          <span className={shell.kpiValue}>{show((p) => formatInt(p.prints))}</span>
          <span className={`${shell.kpiSub} ${styles.mono}`}>
            {show((p) => `${formatInt(p.clicks)} clics · CTR ${formatCtr(p.ctr)} · ${formatInt(p.reach)} alcance`)}
          </span>
          <span className={`${shell.kpiSub} ${styles.mono}`}>{show((p) => `CPM ${formatRatioMoney(p.cpm)}`)}</span>
        </div>
      </section>

      {shown && <StackedDailyCost campaigns={shown.campaigns} daily={shown.daily} range={shown.range} />}

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
        <div className={styles.tableHead}>
          <h3 className={styles.cardTitle}>Campañas</h3>
          <SegmentedControl label="Estado" options={segments} value={segment} onChange={setSegment} />
          <label className={`${shell.search} ${styles.tableSearch}`}>
            <Search size={14} aria-hidden="true" />
            <input
              type="search"
              className={shell.searchInput}
              aria-label="Buscar campaña"
              placeholder="Filtrar por nombre o ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
        <table className={shell.table}>
          <thead>
            <tr>
              <th>Campaña</th>
              <th>Estado</th>
              <th>Objetivo</th>
              <th>Vigencia</th>
              <th className={shell.num}>Costo</th>
              <th className={shell.num}>Impresiones</th>
              <th className={shell.num} title="Suma del alcance de cada día: una persona alcanzada dos días cuenta dos veces">
                Alcance
              </th>
              <th className={shell.num}>Clics</th>
              <th className={shell.num}>CTR</th>
              <th className={shell.num}>CPM</th>
              <th className={shell.num}>CPC</th>
              <th className={shell.num}>Ventas atrib.</th>
              <th className={shell.num}>Unid.</th>
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
                const key = keyOf(c);
                const expanded = open.has(key);
                const name = campaignName(c);
                return (
                  <Fragment key={key}>
                    <tr className={idle ? styles.idle : undefined}>
                      <td>
                        <div className={styles.campaign}>
                          <button
                            type="button"
                            className={styles.expand}
                            aria-expanded={expanded}
                            aria-label={`Ver tendencia diaria de ${name}`}
                            onClick={() => toggle(key)}
                          >
                            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </button>
                          <span className={styles.campaignText}>
                            <span className={shell.campaignName}>{name}</span>
                            <span className={shell.campaignId}>ID {c.campaign_id}</span>
                          </span>
                        </div>
                      </td>
                      <td>
                        {status ? (
                          <span className={shell.keep}>
                            <StatusPill tone={status.tone}>{status.text}</StatusPill>
                          </span>
                        ) : (
                          <span className={shell.muted}>{c.status || '—'}</span>
                        )}
                      </td>
                      <td className={styles.nowrap}>{GOALS[c.goal] || c.goal || '—'}</td>
                      <td className={styles.date}>
                        {/* Breaks only after the dash, as in the screen: never inside a date. */}
                        {c.start_date || c.end_date ? `${formatDate(c.start_date)}\u00a0– ${formatDate(c.end_date)}` : '—'}
                      </td>
                      <td className={shell.num}>{formatSignedMoney(c.cost)}</td>
                      <td className={shell.num}>{formatInt(c.prints)}</td>
                      <td className={shell.num}>{formatInt(c.reach)}</td>
                      <td className={shell.num}>{formatInt(c.clicks)}</td>
                      <td className={shell.num}>{formatCtr(c.ctr)}</td>
                      <td className={shell.num}>{formatRatioMoney(c.cpm)}</td>
                      <td className={shell.num}>{formatRatioMoney(c.cpc)}</td>
                      <td className={shell.num}>{formatSignedMoney(c.attributed_amount)}</td>
                      <td className={shell.num}>{formatInt(c.attributed_units)}</td>
                      <td className={shell.num}>{formatRoas(c.roas)}</td>
                    </tr>
                    {expanded && <TrendRow campaign={c} report={shown} />}
                  </Fragment>
                );
              })}
          </tbody>
          {!loading && visible.length > 0 && (
            <tfoot>
              <tr>
                <td>Total</td>
                <td className={shell.muted}>{`${formatInt(visible.length)} camp.`}</td>
                <td className={`${shell.muted} ${styles.nowrap}`}>
                  {`${formatInt(visible.filter((c) => c.status === 'active').length)} act. · ${formatInt(
                    visible.filter((c) => c.status === 'paused').length,
                  )} paus.`}
                </td>
                <td className={shell.muted}>—</td>
                <td className={shell.num}>{formatSignedMoney(totals.cost)}</td>
                <td className={shell.num}>{formatInt(totals.prints)}</td>
                <td className={shell.num}>{formatInt(totals.reach)}</td>
                <td className={shell.num}>{formatInt(totals.clicks)}</td>
                <td className={shell.num}>{formatCtr(totals.ctr)}</td>
                <td className={shell.num}>{formatRatioMoney(totals.cpm)}</td>
                <td className={shell.num}>{formatRatioMoney(totals.cpc)}</td>
                <td className={shell.num}>{formatSignedMoney(totals.attributed_amount)}</td>
                <td className={shell.num}>{formatInt(totals.attributed_units)}</td>
                <td className={shell.num}>{formatRoas(totals.roas)}</td>
              </tr>
            </tfoot>
          )}
        </table>
        {!loading && campaigns.length > 0 && (
          <p className={styles.tableFoot}>
            Mostrando <strong>{formatInt(visible.length)}</strong> de <strong>{formatInt(campaigns.length)}</strong>{' '}
            campañas registradas
          </p>
        )}
      </div>

      <p className={`${shell.footnote} ${styles.note}`}>
        <Info size={14} aria-hidden="true" /> Costo sin IVA, como lo informa Mercado Libre. Ventas atribuidas por
        Mercado Libre (fecha del evento). Los datos de Display se guardan a diario; Mercado Libre solo conserva 90 días.
      </p>
    </div>
  );
}
