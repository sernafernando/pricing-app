import { useEffect, useRef, useState } from 'react';
import { ArrowUpDown, MoreVertical, SlidersHorizontal } from 'lucide-react';
import SearchInput from '../../SearchInput';
import { calcularRangoPreset } from '../../../utils/dateRangePresets';
import { markupTone } from '../../../utils/ventasMlTone';
import { deltaTone, formatDeltaPct, formatDeltaPp, formatPct, formatUnits } from '../../../utils/metricasMlFormat';
import BoardCard from './BoardCard';
import { formatCompactMoney } from './phoneBoard';
import styles from './MetricasPhone.module.css';

const PERIOD_CHIPS = [
  { key: 'hoy', label: 'Hoy' },
  { key: '7d', label: '7d' },
  { key: 'mesActual', label: 'Mes actual' },
  { key: '30d', label: '30d' },
  { key: '3m', label: '3m' },
];

const DAY_MS = 86400000;
const toneClass = (tone) => (tone ? styles[`tone_${tone}`] || '' : '');
// A delta's colour: up is good, down is bad.
const DELTA_TONES = { up: 'good', down: 'negative' };

/** "Rango…": the custom period, applied only when whole, in order and within the board's cap -- as DateRangeFilter. */
function CustomRange({ range, maxDays, maxDaysMessage, onApply }) {
  const [desde, setDesde] = useState(range.desde);
  const [hasta, setHasta] = useState(range.hasta);
  const inverted = Boolean(desde && hasta && desde > hasta);
  const days = desde && hasta && !inverted ? Math.round((Date.parse(`${hasta}T00:00:00Z`) - Date.parse(`${desde}T00:00:00Z`)) / DAY_MS) + 1 : 0;
  const tooLong = days > maxDays;
  const problem = inverted ? 'La fecha de inicio es posterior a la de fin' : tooLong ? maxDaysMessage : null;
  return (
    <div className={styles.customRange}>
      <label className={styles.dateField}>
        <span>Desde</span>
        <input type="date" value={desde} onChange={(event) => setDesde(event.target.value)} />
      </label>
      <label className={styles.dateField}>
        <span>Hasta</span>
        <input type="date" value={hasta} onChange={(event) => setHasta(event.target.value)} />
      </label>
      <button
        type="button"
        className={styles.applyRange}
        disabled={!desde || !hasta || Boolean(problem)}
        onClick={() => onApply({ desde, hasta, filtro: 'custom' })}
      >
        Aplicar
      </button>
      {problem && (
        <p className={styles.rangeProblem} role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

/** "⋯": the exports, as a small menu that closes on a pick, Escape or a tap outside. */
function ActionsMenu({ actions }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  const labels = actions.map((action) => action.label).join(', ');
  return (
    <div className={styles.menuWrap} ref={ref}>
      <button
        type="button"
        className={styles.iconButton}
        aria-label={`Más acciones: ${labels.toLowerCase()}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <MoreVertical size={20} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          {actions.map(({ label, busyLabel, busy, onSelect }) => (
            <button
              key={label}
              type="button"
              role="menuitem"
              className={styles.menuItem}
              disabled={busy}
              onClick={() => {
                setOpen(false);
                onSelect();
              }}
            >
              {busy ? busyLabel : label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, valueTone, note, noteTone }) {
  return (
    <div className={styles.kpi}>
      <span className={styles.kpiLabel}>{label}</span>
      <span className={`${styles.kpiValue} ${toneClass(valueTone)}`} data-kpi-value>
        {value}
      </span>
      {note && <span className={`${styles.kpiNote} ${toneClass(noteTone)}`}>{note}</span>}
    </div>
  );
}

/** The six KPI cards of the design, from the same `kpis` as the desktop strip (and the same hidden ones). */
function KpiGrid({ kpis, canSeeMargin, tpSolo, noun, isVisible }) {
  if (!kpis) return null;
  const { units, gross, total_gauss: tg, markup, rows_with_sales: withSales, ageing } = kpis;
  const tp = kpis.total_tp ?? null;
  const delta = (value, format) => ({ note: format(value), noteTone: DELTA_TONES[deltaTone(value)] });
  const cards = [
    isVisible('units') && <Kpi key="units" label="Unidades vendidas" value={formatUnits(units.value)} {...delta(units.delta_pct, formatDeltaPct)} />,
    isVisible('gross') && <Kpi key="gross" label="Facturado bruto" value={formatCompactMoney(gross.value)} {...delta(gross.delta_pct, formatDeltaPct)} />,
    canSeeMargin && !tpSolo && tg && isVisible('total_gauss') && (
      <Kpi key="tg" label="Total Gauss" value={formatCompactMoney(tg.value)} valueTone={tg.value < 0 ? 'negative' : null} {...delta(tg.delta_pct, formatDeltaPct)} />
    ),
    canSeeMargin && tpSolo && tp && isVisible('total_tp') && (
      <Kpi key="tp" label="Total TP" value={formatCompactMoney(tp.value)} valueTone={tp.value < 0 ? 'negative' : null} />
    ),
    canSeeMargin && markup && isVisible('markup') && (
      <Kpi
        key="markup"
        label={tpSolo ? 'Markup TP' : 'Markup promedio'}
        value={formatPct(markup.value)}
        valueTone={markupTone(markup.value) === 'negative' ? 'negative' : null}
        {...delta(markup.delta_pp, formatDeltaPp)}
      />
    ),
    isVisible('rows_with_sales') && (
      <Kpi key="rows" label={`${noun} con ventas`} value={formatUnits(withSales.value)} note={`de ${formatUnits(withSales.of_total)}`} />
    ),
    isVisible('ageing') && (
      <Kpi
        key="ageing"
        label="Ageing promedio"
        value={ageing.avg_days == null ? '—' : `${formatUnits(Math.round(ageing.avg_days))} d`}
        note={ageing.over_60 > 0 ? `${formatUnits(ageing.over_60)} con más de 60 d` : null}
        noteTone={ageing.over_60 > 0 ? 'negative' : null}
      />
    ),
  ].filter(Boolean);
  return (
    <section className={styles.kpis} aria-label="Indicadores">
      {cards}
    </section>
  );
}

/**
 * Métricas ML on a phone (design `Main.dc.html`, handoffs `mobile-metricas-pubml-tarea` T1). The page owns every
 * state, request and filter (the desktop's own); this lays them out for a narrow screen: a sticky header with the
 * search, period chips, "Filtros (n)" and the sort, the KPI cards in two columns, and one card per board row with
 * "Cargar 20 más" instead of pages. The filters themselves live in `filterSheet` (a FilterSheet the page builds).
 */
export default function MetricasPhone({
  freshness,
  banners,
  range,
  maxDays,
  maxDaysMessage,
  onRangeChange,
  searchQuery,
  onSearchChange,
  filterChips,
  filterCount,
  onOpenFilters,
  filterSheet,
  sortOptions,
  sort,
  onSortChange,
  actions,
  kpis,
  kpiVisible,
  canSeeMargin,
  tpOn,
  tpSolo,
  groupBy,
  noun,
  rows,
  total,
  withSalesCount,
  loading,
  errorKind,
  expanded,
  subRows,
  onToggleExpand,
  onLoadMore,
  loadingMore,
  moreError,
}) {
  const [rangeOpen, setRangeOpen] = useState(range.filtro === 'custom');
  const now = new Date();
  const kind = groupBy === 'group' ? 'group' : groupBy === 'publication' ? 'publication' : 'product';
  const nounTitle = noun.charAt(0).toUpperCase() + noun.slice(1);
  const pickPreset = (filtro) => {
    const rango = calcularRangoPreset(filtro);
    if (!rango) return;
    setRangeOpen(false);
    onRangeChange({ ...rango, filtro });
  };
  const sortValue = `${sort.key}:${sort.desc ? 'desc' : 'asc'}`;
  const sortLabel = sortOptions.find((option) => option.value === sort.key)?.label ?? 'Ordenar';
  const hasMore = rows.length < total;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Métricas ML</h1>
          {freshness && <span className={styles.freshness}>act. {freshness}</span>}
          <ActionsMenu actions={actions} />
        </div>
        <SearchInput
          value={searchQuery}
          onChange={onSearchChange}
          debounce={400}
          placeholder="Título, MLA, SKU/EAN o producto"
          className={styles.search}
          size="lg"
        />
        <div className={styles.periods} role="group" aria-label="Período">
          {PERIOD_CHIPS.map(({ key, label }) => (
            <button key={key} type="button" className={styles.chip} aria-pressed={range.filtro === key} onClick={() => pickPreset(key)}>
              {label}
            </button>
          ))}
          <button
            type="button"
            className={styles.chip}
            aria-pressed={range.filtro === 'custom'}
            aria-expanded={rangeOpen}
            onClick={() => setRangeOpen((prev) => !prev)}
          >
            Rango…
          </button>
        </div>
        {rangeOpen && (
          <CustomRange
            key={`${range.desde}-${range.hasta}`}
            range={range}
            maxDays={maxDays}
            maxDaysMessage={maxDaysMessage}
            onApply={(next) => {
              setRangeOpen(false);
              onRangeChange(next);
            }}
          />
        )}
        <div className={styles.toolbar}>
          <button type="button" className={styles.toolButton} onClick={onOpenFilters}>
            <SlidersHorizontal size={16} aria-hidden="true" />
            Filtros
            {filterCount > 0 && <span className={styles.badge}>{filterCount}</span>}
          </button>
          <label className={styles.toolButton}>
            <ArrowUpDown size={16} aria-hidden="true" />
            <span aria-hidden="true">
              {sortLabel} {sort.desc ? '↓' : '↑'}
            </span>
            <select
              className={styles.sortSelect}
              aria-label="Ordenar por"
              value={sortValue}
              onChange={(event) => {
                const [key, dir] = event.target.value.split(':');
                onSortChange({ key, desc: dir === 'desc' });
              }}
            >
              {sortOptions.flatMap(({ value, label }) => [
                <option key={`${value}:desc`} value={`${value}:desc`}>
                  {label} ↓
                </option>,
                <option key={`${value}:asc`} value={`${value}:asc`}>
                  {label} ↑
                </option>,
              ])}
              {!sortOptions.some((option) => option.value === sort.key) && <option value={sortValue}>Otro orden</option>}
            </select>
          </label>
        </div>
        {filterChips.length > 0 && (
          <ul className={styles.activeChips} aria-label="Filtros activos">
            {filterChips.map((chip) => (
              <li key={chip} className={styles.activeChip}>
                {chip}
              </li>
            ))}
          </ul>
        )}
      </header>

      {banners}

      <KpiGrid kpis={kpis} canSeeMargin={canSeeMargin} tpSolo={tpSolo} noun={nounTitle} isVisible={kpiVisible} />

      <section className={styles.list} aria-label={nounTitle} aria-busy={loading}>
        <div className={styles.listHead}>
          <h2 className={styles.listTitle}>{nounTitle}</h2>
          <span className={styles.listCount}>
            {formatUnits(withSalesCount)} con ventas · {total === 0 ? 0 : 1}–{formatUnits(rows.length)} de {formatUnits(total)}
          </span>
        </div>
        {rows.map((row) => (
          <BoardCard
            key={row.key}
            row={row}
            kind={kind === 'group' && !row.child_level ? 'product' : kind}
            canSeeMargin={canSeeMargin}
            tpOn={tpOn}
            tpSolo={tpSolo}
            expanded={expanded}
            subRows={subRows}
            onToggleExpand={onToggleExpand}
            now={now}
          />
        ))}
        {!loading && rows.length === 0 && !errorKind && <p className={styles.empty}>No hay {noun} que coincidan con los filtros.</p>}
        {moreError && (
          <p className={styles.moreError} role="alert">
            No se pudieron traer más {noun}.
          </p>
        )}
        {hasMore && (
          <button type="button" className={styles.loadMore} onClick={onLoadMore} disabled={loadingMore}>
            {loadingMore ? 'Cargando…' : moreError ? 'Reintentar' : 'Cargar 20 más'}
          </button>
        )}
      </section>

      {filterSheet}
    </div>
  );
}
