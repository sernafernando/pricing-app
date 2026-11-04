/**
 * AportesPorAporte — the "Por aporte" view of Aportes de marcas, after the owner-approved Stitch screen 55853ac1.
 *
 * One row per aporte of either channel whose range touches the page's range (`GET /ml-ads/contributions`), with what
 * it covers there as Métricas ML subtracts it, and "Cargado": who loaded it and when, from the aporte's audit rows.
 * Above, the period in tiles (each channel against its own cost, and the Product Ads cost no aporte can cover) and
 * split by brand. The search, brand and channel filters work on the loaded rows, without a new request.
 *
 * The page owns the range, the forms and the delete confirmation: `onEdit(row)` and `onDelete(row)` hand it the row;
 * a change to `refreshKey` asks again. Every row can be edited, Display ones included.
 */
import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Clock, Info, Pencil, Search, Trash2 } from 'lucide-react';
import api from '../services/api';
import { SegmentedControl, StatusPill } from '../components/kit';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import { formatSignedMoney } from '../utils/ventasMlTone';
import { scopeOf } from '../utils/aportesScope';
import { dayMonth, stampDay } from '../utils/aportesDates';
import AportesHistorial from './AportesHistorial';
import shell from './AportesAdsML.module.css';
import styles from './AportesPorAporte.module.css';

const CHANNELS = [
  { value: 'all', label: 'Todos' },
  { value: 'product_ads', label: 'Product Ads' },
  { value: 'display', label: 'Display' },
];
const CHANNEL_BADGES = { product_ads: { text: 'Product Ads', tone: 'info' }, display: { text: 'Display', tone: 'purple' } };
const KINDS = { percentage: 'Porcentaje', fixed_amount: 'Monto fijo' };
const SETTLEMENT_BADGES = {
  full: { text: 'Se recibe todo', tone: 'info' },
  refund_difference: { text: 'Devuelve diferencia', tone: 'warning' },
};

const percent = (value) => `${value.toLocaleString('es-AR', { maximumFractionDigits: 1 })} %`;
const share = (part, whole) => (whole > 0 ? percent((part / whole) * 100) : '—');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const sum = (rows) => rows.reduce((total, row) => total + (row.covered || 0), 0);

/** Shown, grouped and filtered by; an aporte saved before the brand was required has none. Never written back. */
const brandOf = (row) => row.brand || 'Sin marca';

function useAportes(range, refreshKey) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const latest = useRef(0);
  useEffect(() => {
    // Half-typed or inverted dates: wait, as the campaigns view does, instead of showing the backend's 422.
    if (!(range.from && range.to && range.from <= range.to)) return;
    const request = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    api
      .get('/ml-ads/contributions', { params: { date_from: range.from, date_to: range.to } })
      .then(({ data }) => {
        if (request === latest.current) setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        if (request === latest.current)
          setState({ data: null, loading: false, error: apiErrorMessage(err, 'No se pudieron cargar los aportes') });
      });
  }, [range.from, range.to, refreshKey]);
  return state;
}

function Tiles({ rows, totals }) {
  const brands = new Set(rows.map(brandOf)).size;
  const pads = sum(rows.filter((r) => r.channel === 'product_ads'));
  const display = sum(rows.filter((r) => r.channel === 'display'));
  return (
    <section className={shell.kpis} aria-label="Resumen de aportes por aporte">
      <div className={shell.kpi}>
        <span className={shell.kpiLabel}>Aportes del período</span>
        <span className={shell.kpiValue}>{formatSignedMoney(sum(rows))}</span>
        <span className={shell.kpiSub}>{`${plural(brands, 'marca', 'marcas')} · ${plural(rows.length, 'aporte', 'aportes')}`}</span>
      </div>
      <div className={shell.kpi}>
        <span className={shell.kpiLabel}>Product Ads</span>
        <span className={shell.kpiValue}>{formatSignedMoney(pads)}</span>
        <span className={`${shell.kpiSub} ${styles.subPads}`}>
          {`${share(pads, totals.product_ads_cost)} del costo de Product Ads`}
        </span>
      </div>
      <div className={shell.kpi}>
        <span className={shell.kpiLabel}>Display</span>
        <span className={shell.kpiValue}>{formatSignedMoney(display)}</span>
        <span className={`${shell.kpiSub} ${styles.subDisplay}`}>{`${share(display, totals.display_cost)} del costo de Display`}</span>
      </div>
      <div className={`${shell.kpi} ${styles.kpiWarning}`}>
        <span className={styles.kpiHead}>
          <span className={shell.kpiLabel}>Sin campaña</span>
          <StatusPill tone="warning">Atención</StatusPill>
        </span>
        <span className={shell.kpiValue}>{formatSignedMoney(totals.no_campaign_cost)}</span>
        <span className={shell.kpiSub}>Costo de Product Ads sin campaña: ningún aporte lo cubre</span>
      </div>
    </section>
  );
}

function ByBrand({ rows }) {
  const total = sum(rows);
  const byBrand = new Map();
  for (const row of rows) byBrand.set(brandOf(row), (byBrand.get(brandOf(row)) || 0) + (row.covered || 0));
  const brands = [...byBrand].sort(([, a], [, b]) => b - a);
  // A brand that only pays Display gets the Display color, as in the design.
  const onlyDisplay = (brand) => rows.every((row) => brandOf(row) !== brand || row.channel === 'display');
  return (
    <section className={styles.brands} aria-label="Por marca">
      <header className={styles.brandsHeader}>
        <h3 className={styles.brandsTitle}>Por marca</h3>
        <span className={shell.muted}>Distribución de aportes del período</span>
      </header>
      <ul className={styles.brandList}>
        {brands.map(([brand, amount]) => (
          <li key={brand} className={styles.brand}>
            <span className={styles.brandName}>{brand}</span>
            <span className={styles.brandAmount} data-money>
              {formatSignedMoney(amount)}
              <span className={styles.brandShare}>({share(amount, total)})</span>
            </span>
            <span className={styles.track} aria-hidden="true">
              <span
                className={`${styles.bar} ${onlyDisplay(brand) ? styles.barDisplay : ''}`}
                data-channel={onlyDisplay(brand) ? 'display' : 'product_ads'}
                style={{ width: `${total > 0 ? (amount / total) * 100 : 0}%` }} />
            </span>
          </li>
        ))}
      </ul>
      <p className={styles.brandsTotal}>
        Total <span data-money>{formatSignedMoney(total)}</span>
      </p>
    </section>
  );
}

function Row({ row, canManage, onEdit, onDelete, onHistory }) {
  const scope = scopeOf(row);
  const channel = CHANNEL_BADGES[row.channel];
  const settlement = SETTLEMENT_BADGES[row.settlement];
  return (
    <tr>
      <td className={styles.brandCell}>{brandOf(row)}</td>
      <td>
        <span className={styles.nowrap}>{channel && <StatusPill tone={channel.tone}>{channel.text}</StatusPill>}</span>
      </td>
      <td>
        <span className={styles.scope}>
          <span className={shell.campaignName}>{scope.name}</span>
          <span className={shell.campaignId}>{scope.detail}</span>
        </span>
      </td>
      <td>
        <span className={styles.kind}>
          {KINDS[row.kind] || row.kind}
          {settlement && (
            <span className={styles.nowrap}>
              <StatusPill tone={settlement.tone}>{settlement.text}</StatusPill>
            </span>
          )}
        </span>
      </td>
      <td className={`${shell.num} ${styles.nowrap}`}>
        {row.kind === 'percentage' ? percent(row.value) : formatSignedMoney(row.value)}
      </td>
      <td className={`${styles.range} ${styles.nowrap}`}>{`${dayMonth(row.date_from)} → ${dayMonth(row.date_to)}`}</td>
      <td className={`${shell.num} ${shell.positive}`}>{formatSignedMoney(row.covered)}</td>
      <td>
        <span className={styles.loaded}>
          <span>{`${row.loaded_by || 'Sin dato'} · ${stampDay(row.loaded_at)}`}</span>
          {row.edited_at && <span className={shell.muted}>{`Editado ${stampDay(row.edited_at)}`}</span>}
        </span>
      </td>
      <td>
        {/* Pencil, clock, trash, as the design; the history is read-only, so it needs no permission to manage. */}
        <span className={shell.actions}>
          {canManage && (
            <button
              type="button"
              className={shell.btnIcon}
              aria-label={`Editar aporte de ${brandOf(row)}`}
              title="Editar"
              onClick={() => onEdit(row)}
            >
              <Pencil size={14} />
            </button>
          )}
          <button
            type="button"
            className={shell.btnIcon}
            aria-label={`Historial del aporte de ${brandOf(row)}`}
            title="Historial"
            onClick={() => onHistory(row)}
          >
            <Clock size={14} />
          </button>
          {canManage && (
            <button
              type="button"
              className={`${shell.btnIcon} ${shell.btnIconDanger}`}
              aria-label={`Borrar aporte de ${brandOf(row)}`}
              title="Borrar"
              onClick={() => onDelete(row)}
            >
              <Trash2 size={14} />
            </button>
          )}
        </span>
      </td>
    </tr>
  );
}

export default function AportesPorAporte({ range, canManage, refreshKey, onEdit, onDelete }) {
  const { data, loading, error } = useAportes(range, refreshKey);
  const [search, setSearch] = useState('');
  const [historyOf, setHistoryOf] = useState(null);
  const [brand, setBrand] = useState('');
  const [channel, setChannel] = useState('all');
  const rows = data?.contributions ?? [];
  const brands = [...new Set(rows.map(brandOf))].sort();
  // A range without the chosen brand drops the filter instead of hiding every row behind 'Todas'.
  const brandFilter = brands.includes(brand) ? brand : '';
  const needle = search.trim().toLowerCase();
  const visible = rows.filter(
    (r) =>
      (!needle || `${brandOf(r)} ${scopeOf(r).name} ${r.campaign_id ?? ''}`.toLowerCase().includes(needle)) &&
      (!brandFilter || brandOf(r) === brandFilter) &&
      (channel === 'all' || r.channel === channel),
  );
  return (
    <>
      {data && <Tiles rows={rows} totals={data.totals} />}
      {data && rows.length > 0 && <ByBrand rows={rows} />}

      <div className={shell.toolbar}>
        <label className={shell.search}>
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            className={shell.searchInput}
            aria-label="Buscar marca o campaña"
            placeholder="Buscar marca o campaña…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className={shell.advertiser}>
          <span>Marca</span>
          <select className={shell.advertiserSelect} value={brandFilter} onChange={(e) => setBrand(e.target.value)}>
            <option value="">Todas</option>
            {brands.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <span className={styles.channels}>
          <SegmentedControl label="Canal" options={CHANNELS} value={channel} onChange={setChannel} />
        </span>
      </div>

      {error && (
        <div className={shell.alertError} role="alert">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      <div className={shell.tableCard}>
        <table className={shell.table} aria-label="Aportes del período">
          <thead>
            <tr>
              <th>Marca</th>
              <th>Canal</th>
              <th>Campaña / alcance</th>
              <th>Tipo</th>
              <th className={shell.num}>Valor</th>
              <th>Rango</th>
              <th className={shell.num}>Cubre en el período</th>
              <th>Cargado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className={shell.muted}>Cargando...</td>
              </tr>
            )}
            {!loading && data && rows.length === 0 && (
              <tr>
                <td colSpan={9} className={shell.muted}>No hay aportes que toquen el período.</td>
              </tr>
            )}
            {!loading && rows.length > 0 && visible.length === 0 && (
              <tr>
                <td colSpan={9} className={shell.muted}>Ningún aporte coincide con los filtros.</td>
              </tr>
            )}
            {!loading &&
              visible.map((row) => (
                <Row
                  key={row.id}
                  row={row}
                  canManage={canManage}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onHistory={setHistoryOf}
                />
              ))}
          </tbody>
          {!loading && rows.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={6}>{`Total (${plural(visible.length, 'aporte', 'aportes')})`}</td>
                <td className={`${shell.num} ${shell.positive}`}>{formatSignedMoney(sum(visible))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className={shell.footnote}>
        <Info size={14} aria-hidden="true" /> Un aporte borrado deja de contar y sale de la lista; queda guardado quién
        lo borró y cuándo. &apos;Devuelve diferencia&apos; cuenta como máximo lo gastado en el rango.
      </p>

      {historyOf && <AportesHistorial aporte={historyOf} onClose={() => setHistoryOf(null)} />}
    </>
  );
}
