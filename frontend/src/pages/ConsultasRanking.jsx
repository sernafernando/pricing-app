import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Search,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUp,
  ArrowDown,
  AlertCircle,
  PackageSearch,
  Warehouse,
  RefreshCw,
} from 'lucide-react';
import SearchInput from '../components/SearchInput';
import { useConsultasRanking } from '../hooks/useConsultasRanking';
import { getRankingFacets, getRankingKpis, getRankingResumen, getStockStatus, refreshStock } from '../services/consultasService';
import styles from './ConsultasRanking.module.css';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FALLBACK_DEPOSITOS = [{ id: 1, label: 'Depósito 1' }];
const PAGE_SIZE_OPTIONS = [50, 100, 200];

const COLUMNS = [
  { key: 'codigo', label: 'Código', sortable: true, align: 'left', sticky: true },
  { key: 'descripcion', label: 'Descripción', sortable: true, align: 'left' },
  { key: 'marca', label: 'Marca', sortable: true, align: 'left' },
  { key: 'categoria', label: 'Categoría', sortable: true, align: 'left' },
  { key: null, label: 'PM', sortable: false, align: 'left' },
  { key: 'dias_sin_venta', label: 'Días sin venta', sortable: true, align: 'right' },
  { key: null, label: 'Ageing ERP', sortable: false, align: 'right' },
  { key: 'last_purchase_date', label: 'Última compra', sortable: true, align: 'left' },
  { key: 'total_stock', label: 'Stock', sortable: true, align: 'right' },
  { key: 'valor_costo_ars', label: 'Valor costo', sortable: true, align: 'right' },
  { key: 'valor_venta', label: 'Valor venta', sortable: true, align: 'right' },
];

// ---------------------------------------------------------------------------
// Facets hook
// ---------------------------------------------------------------------------

function useFacets() {
  const [facets, setFacets] = useState({ marcas: [], categorias: [], pms: [], depositos: [] });
  const [facetsLoading, setFacetsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setFacetsLoading(true);
    getRankingFacets()
      .then((data) => { if (!cancelled) setFacets(data); })
      .catch(() => { /* non-fatal */ })
      .finally(() => { if (!cancelled) setFacetsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { facets, facetsLoading };
}

// ---------------------------------------------------------------------------
// Resumen hook
// ---------------------------------------------------------------------------

function useResumen({ enabled, marca, categoria, pm, storIds, incluirSinStock, incluirCombos, groupBy }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    if (abortRef.current) abortRef.current.cancelled = true;
    const token = { cancelled: false };
    abortRef.current = token;

    setLoading(true);
    setError(null);

    getRankingResumen({ marca, categoria, pm, stor_ids: storIds, incluir_sin_stock: incluirSinStock, incluir_combos: incluirCombos, group_by: groupBy })
      .then((result) => { if (!token.cancelled) { setData(result); setLoading(false); } })
      .catch((err) => {
        if (token.cancelled) return;
        setError(err?.response?.data?.detail || err?.message || 'Error al cargar resumen');
        setLoading(false);
      });

    return () => { token.cancelled = true; };
  }, [enabled, marca, categoria, pm, storIds, incluirSinStock, incluirCombos, groupBy]);

  return { data, loading, error };
}

// ---------------------------------------------------------------------------
// KPIs hook
// ---------------------------------------------------------------------------

function useKpis({ marca, categoria, pm, storIds, incluirSinStock, incluirCombos, q }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    if (abortRef.current) abortRef.current.cancelled = true;
    const token = { cancelled: false };
    abortRef.current = token;

    setLoading(true);

    getRankingKpis({ marca, categoria, pm, stor_ids: storIds, incluir_sin_stock: incluirSinStock, incluir_combos: incluirCombos, q: q || null })
      .then((result) => { if (!token.cancelled) { setData(result); setLoading(false); } })
      .catch(() => {
        if (token.cancelled) return;
        // Non-fatal: KPI cards silently fail — table still works
        setLoading(false);
      });

    return () => { token.cancelled = true; };
  }, [marca, categoria, pm, storIds, incluirSinStock, incluirCombos, q]);

  return { data, loading };
}

// ---------------------------------------------------------------------------
// Stock sync hook
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 8000;
const POLL_MAX_TRIES = 40; // ~5 min cap

function useStockSync({ onSyncComplete }) {
  const [lastUpdated, setLastUpdated] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState(null);
  const pollRef = useRef(null);
  const baselineRef = useRef(null);
  const triesRef = useRef(0);

  // Fetch current status on mount
  useEffect(() => {
    getStockStatus()
      .then((data) => {
        setLastUpdated(data.last_updated ?? null);
        if (data.syncing) {
          // A sync was already in progress — enter polling mode
          baselineRef.current = data.last_updated;
          setSyncing(true);
          _startPolling();
        }
      })
      .catch(() => { /* non-fatal */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function _stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    triesRef.current = 0;
  }

  function _startPolling() {
    _stopPolling();
    triesRef.current = 0;
    pollRef.current = setInterval(() => {
      triesRef.current += 1;

      getStockStatus()
        .then((data) => {
          const baseline = baselineRef.current;
          const isNewer = data.last_updated && (
            !baseline || new Date(data.last_updated) > new Date(baseline)
          );
          const done = isNewer || (!data.syncing && triesRef.current > 1);

          if (done) {
            _stopPolling();
            setSyncing(false);
            setSyncMessage(null);
            setLastUpdated(data.last_updated ?? null);
            onSyncComplete();
          } else if (triesRef.current >= POLL_MAX_TRIES) {
            _stopPolling();
            setSyncing(false);
            setSyncMessage('La sincronización tardó más de lo esperado. Reintentá en unos minutos.');
          }
        })
        .catch(() => { /* poll failure is silent */ });
    }, POLL_INTERVAL_MS);
  }

  const triggerRefresh = useCallback(async () => {
    if (syncing) return;

    // Capture baseline before launch
    baselineRef.current = lastUpdated;
    setSyncing(true);
    setSyncMessage(null);

    try {
      await refreshStock();
      _startPolling();
    } catch {
      setSyncing(false);
      setSyncMessage('Error al iniciar la sincronización.');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncing, lastUpdated]);

  // Cleanup on unmount
  useEffect(() => () => _stopPolling(), []);

  return { lastUpdated, syncing, syncMessage, triggerRefresh };
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatARS(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS', maximumFractionDigits: 0 }).format(value);
}

function formatUSD(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return dateStr;
  }
}

function formatDateTime(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' })
      + ' '
      + d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return isoStr;
  }
}

// ---------------------------------------------------------------------------
// Stock refresh bar
// ---------------------------------------------------------------------------

function StockRefreshBar({ lastUpdated, syncing, syncMessage, onRefresh }) {
  const label = lastUpdated
    ? `Stock actualizado: ${formatDateTime(lastUpdated)}`
    : 'Stock: sin sincronizar';

  return (
    <div className={styles.stockBar} role="region" aria-label="Estado de stock">
      <span className={styles.stockLabel}>{label}</span>
      {syncMessage && (
        <span className={styles.stockMessage} role="alert">{syncMessage}</span>
      )}
      <button
        type="button"
        className={`${styles.stockRefreshBtn} ${syncing ? styles.stockRefreshBtnSyncing : ''}`}
        onClick={onRefresh}
        disabled={syncing}
        aria-label={syncing ? 'Actualizando stock…' : 'Actualizar stock'}
        title={syncing ? 'Sincronización en curso…' : 'Actualizar stock desde ERP'}
      >
        <RefreshCw
          size={14}
          className={syncing ? styles.spinIcon : ''}
          aria-hidden="true"
        />
        <span>{syncing ? 'Actualizando…' : 'Actualizar stock'}</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI cards row
// ---------------------------------------------------------------------------

function KpiCards({ data, loading }) {
  if (loading && !data) {
    return <div className={styles.kpiRow} aria-busy="true" />;
  }
  if (!data) return null;

  const pct = data.pct_capital_muerto;
  const isHighMuerto = pct != null && pct >= 30;

  return (
    <div className={styles.kpiRow} role="region" aria-label="KPIs de capital">
      {/* Card 1: Capital holdeado */}
      <div className={styles.kpiCard}>
        <span className={styles.kpiLabel}>Capital holdeado</span>
        <span className={styles.kpiValue}>{formatARS(data.capital_costo_ars)}</span>
        <span className={styles.kpiSub}>{formatUSD(data.capital_costo_usd)}</span>
      </div>

      {/* Card 2: Stock muerto */}
      <div className={styles.kpiCard}>
        <span className={styles.kpiLabel}>Stock muerto</span>
        <span className={`${styles.kpiValue} ${isHighMuerto ? styles.kpiValueDanger : ''}`}>
          {formatARS(data.capital_muerto_ars)}
        </span>
        <span className={`${styles.kpiSub} ${isHighMuerto ? styles.kpiSubDanger : ''}`}>
          {pct != null ? `${pct.toFixed(1)}% del capital` : '—'}
        </span>
      </div>

      {/* Card 3: SKUs */}
      <div className={styles.kpiCard}>
        <span className={styles.kpiLabel}>SKUs</span>
        <span className={styles.kpiValue}>
          {data.total_productos != null ? data.total_productos.toLocaleString('es-AR') : '—'}
        </span>
        <span className={styles.kpiSub}>con stock</span>
      </div>

      {/* Card 4: Valor potencial venta */}
      <div className={styles.kpiCard}>
        <span className={styles.kpiLabel}>Valor potencial venta</span>
        <span className={styles.kpiValue}>{formatARS(data.capital_venta_ars)}</span>
        <span className={styles.kpiSub}>&nbsp;</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Días sin venta color class
// ---------------------------------------------------------------------------

function diasClass(dias) {
  if (dias == null) return '';
  if (dias < 90) return styles.diasGreen;
  if (dias <= 365) return styles.diasAmber;
  return styles.diasRed;
}

// ---------------------------------------------------------------------------
// Días sin venta gauge bar
// ---------------------------------------------------------------------------

const GAUGE_MAX = 730; // ~2 years fills the bar

function diasFillClass(dias) {
  if (dias < 90) return styles.gaugeFillGreen;
  if (dias <= 365) return styles.gaugeFillAmber;
  return styles.gaugeFillRed;
}

function DiasGauge({ dias }) {
  if (dias == null) return <span>—</span>;
  const pct = Math.min(Math.max(dias / GAUGE_MAX, 0), 1) * 100;
  return (
    <span
      className={`${styles.diasGaugeWrap} ${diasClass(dias)}`}
      aria-label={`${dias} días sin venta`}
    >
      <span className={styles.gaugeTrack} aria-hidden="true">
        <span
          className={`${styles.gaugeFill} ${diasFillClass(dias)}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`${styles.diasMono}`}>{dias}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Cost cell: dual-currency stacked display
// ---------------------------------------------------------------------------

function CostCell({ valorCostoArs, valorCostoUsd }) {
  if (valorCostoArs == null && valorCostoUsd == null) return <span>—</span>;
  return (
    <span className={styles.costCell}>
      <span className={styles.costRowPrimary}>
        <span className={styles.costTag}>USD</span>
        <span className={styles.costAmountPrimary}>{formatUSD(valorCostoUsd)}</span>
      </span>
      <span className={styles.costRowSecondary}>
        <span className={styles.costTag}>ARS</span>
        <span className={styles.costAmountSecondary}>{formatARS(valorCostoArs)}</span>
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Depot popover
// ---------------------------------------------------------------------------

function DepotPopover({ depositos, storIds, onApply, onClose }) {
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState(storIds);

  const filtered = depositos.filter((d) =>
    d.label.toLowerCase().includes(search.toLowerCase())
  );

  function toggleAll() {
    if (draft.length === depositos.length) {
      // Keep at least one
      setDraft([depositos[0]?.id].filter(Boolean));
    } else {
      setDraft(depositos.map((d) => d.id));
    }
  }

  function toggle(id) {
    if (draft.includes(id)) {
      if (draft.length === 1) return;
      setDraft(draft.filter((d) => d !== id));
    } else {
      setDraft([...draft, id]);
    }
  }

  const allSelected = draft.length === depositos.length;

  return (
    <div className={styles.popover} role="dialog" aria-label="Seleccionar depósitos">
      <div className={styles.popoverSearch}>
        <Search size={14} className={styles.popoverSearchIcon} aria-hidden="true" />
        <input
          type="text"
          className={styles.popoverSearchInput}
          placeholder="Buscar depósito…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          autoFocus
        />
      </div>
      <div className={styles.popoverAllRow} onClick={toggleAll}>
        <input
          type="checkbox"
          checked={allSelected}
          onChange={toggleAll}
          onClick={(e) => e.stopPropagation()}
          aria-label="Todos los depósitos"
        />
        <span>{allSelected ? 'Limpiar selección' : 'Todos'}</span>
      </div>
      <div className={styles.popoverList}>
        {filtered.map((depot) => {
          const selected = draft.includes(depot.id);
          return (
            <label
              key={depot.id}
              className={`${styles.popoverItem} ${selected ? styles.popoverItemSelected : ''}`}
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={() => toggle(depot.id)}
              />
              <span>{depot.label}</span>
            </label>
          );
        })}
        {filtered.length === 0 && (
          <div className={styles.popoverEmpty}>Sin resultados</div>
        )}
      </div>
      <div className={styles.popoverFooter}>
        <button className={styles.popoverCancel} onClick={onClose}>Cancelar</button>
        <button className={styles.popoverApply} onClick={() => onApply([...draft].sort((a, b) => a - b))}>
          Aplicar
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Segmented control
// ---------------------------------------------------------------------------

function SegmentedControl({ options, value, onChange }) {
  return (
    <div className={styles.segmented} role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          role="tab"
          aria-selected={value === opt.value}
          className={`${styles.segmentedBtn} ${value === opt.value ? styles.segmentedBtnActive : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toggle switch
// ---------------------------------------------------------------------------

function ToggleSwitch({ checked, onChange, label, id }) {
  return (
    <label className={styles.toggle} htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        className={styles.toggleInput}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className={styles.toggleTrack} aria-hidden="true">
        <span className={styles.toggleThumb} />
      </span>
      <span className={styles.toggleLabel}>{label}</span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------

function Toolbar({
  facets, facetsLoading,
  marca, setMarca,
  categoria, setCategoria,
  pm, setPm,
  storIds, setStorIds,
  incluirSinStock, setIncluirSinStock,
  incluirCombos, setIncluirCombos,
  busqueda, setBusqueda,
}) {
  const depositos = facets.depositos?.length > 0 ? facets.depositos : FALLBACK_DEPOSITOS;
  const [depotOpen, setDepotOpen] = useState(false);
  const depotRef = useRef(null);
  const btnRef = useRef(null);

  // Close on outside click or Escape
  useEffect(() => {
    if (!depotOpen) return;
    function onMouseDown(e) {
      if (depotRef.current && !depotRef.current.contains(e.target) && btnRef.current && !btnRef.current.contains(e.target)) {
        setDepotOpen(false);
      }
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') setDepotOpen(false);
    }
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [depotOpen]);

  const selectedDepotNames = depositos.filter((d) => storIds.includes(d.id));

  function applyDepot(ids) {
    setStorIds(ids);
    setDepotOpen(false);
  }

  return (
    <div className={styles.toolbar}>
      {/* Search — reuse shared SearchInput (icon + clear handled internally) */}
      <SearchInput
        value={busqueda}
        onChange={setBusqueda}
        placeholder="Buscar producto…"
        size="sm"
        className={styles.searchWrap}
      />

      <div className={styles.toolbarDivider} />

      {/* Marca */}
      <div className={styles.filterGroup}>
        <span className={styles.filterGroupLabel}>Marca</span>
        <button
          type="button"
          className={`${styles.dropBtn} ${marca ? styles.dropBtnActive : ''}`}
          title="Filtrar por marca"
        >
          <span className={styles.dropBtnValue}>{marca || 'Todas'}</span>
          <ChevronDown size={13} aria-hidden="true" />
          <select
            className={styles.dropBtnSelect}
            value={marca}
            onChange={(e) => setMarca(e.target.value)}
            disabled={facetsLoading}
            aria-label="Filtrar por marca"
          >
            <option value="">Todas</option>
            {facets.marcas.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </button>
      </div>

      {/* Categoría */}
      <div className={styles.filterGroup}>
        <span className={styles.filterGroupLabel}>Categoría</span>
        <button
          type="button"
          className={`${styles.dropBtn} ${categoria ? styles.dropBtnActive : ''}`}
          title="Filtrar por categoría"
        >
          <span className={styles.dropBtnValue}>{categoria || 'Todas'}</span>
          <ChevronDown size={13} aria-hidden="true" />
          <select
            className={styles.dropBtnSelect}
            value={categoria}
            onChange={(e) => setCategoria(e.target.value)}
            disabled={facetsLoading}
            aria-label="Filtrar por categoría"
          >
            <option value="">Todas</option>
            {facets.categorias.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </button>
      </div>

      {/* PM */}
      <div className={styles.filterGroup}>
        <span className={styles.filterGroupLabel}>PM</span>
        <button
          type="button"
          className={`${styles.dropBtn} ${pm ? styles.dropBtnActive : ''}`}
          title="Filtrar por PM"
        >
          <span className={styles.dropBtnValue}>{pm || 'Todos'}</span>
          <ChevronDown size={13} aria-hidden="true" />
          <select
            className={styles.dropBtnSelect}
            value={pm}
            onChange={(e) => setPm(e.target.value)}
            disabled={facetsLoading}
            aria-label="Filtrar por PM"
          >
            <option value="">Todos</option>
            {facets.pms.map((p) => <option key={p} value={p}>{p}</option>)}
            <option value="sin_pm">Sin PM</option>
          </select>
        </button>
      </div>

      {/* Depósitos */}
      <div className={styles.filterGroup} style={{ position: 'relative' }}>
        <span className={styles.filterGroupLabel}>Depósitos</span>
        <button
          ref={btnRef}
          type="button"
          className={`${styles.depotBtn} ${storIds.length > 0 ? styles.depotBtnActive : ''}`}
          onClick={() => setDepotOpen((v) => !v)}
          aria-expanded={depotOpen}
          aria-haspopup="dialog"
          aria-label={`Depósitos: ${selectedDepotNames.length} seleccionados`}
        >
          <Warehouse size={14} aria-hidden="true" />
          <span>Depósitos</span>
          <span className={styles.depotBadge}>{storIds.length}</span>
        </button>
        {depotOpen && (
          <div ref={depotRef} className={styles.popoverAnchor}>
            <DepotPopover
              depositos={depositos}
              storIds={storIds}
              onApply={applyDepot}
              onClose={() => setDepotOpen(false)}
            />
          </div>
        )}
      </div>

      <div className={styles.toolbarSpacer} />

      {/* Sin stock toggle */}
      <ToggleSwitch
        id="toggle-sin-stock"
        checked={incluirSinStock}
        onChange={setIncluirSinStock}
        label="Sin stock"
      />

      {/* Combos toggle */}
      <ToggleSwitch
        id="toggle-combos"
        checked={incluirCombos}
        onChange={setIncluirCombos}
        label="Combos"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detalle table
// ---------------------------------------------------------------------------

function DetalleTable({ items, total, loading, error, ordenColumnas, handleOrdenar, getIconoOrden, getNumeroOrden, page, pageSize, totalPages, goToPage, onPageSizeChange }) {
  const startRow = (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);

  return (
    <>
      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead className={styles.thead}>
            <tr>
              {COLUMNS.map((col, idx) => {
                const numOrden = col.key ? getNumeroOrden(col.key) : null;
                const isActive = col.key && ordenColumnas.some((o) => o.columna === col.key);
                return (
                  <th
                    key={col.key ?? `col-${idx}`}
                    className={[
                      styles.th,
                      col.sticky ? styles.thSticky : '',
                      col.align === 'right' ? styles.thRight : '',
                      isActive ? styles.thActive : '',
                      col.sortable ? styles.thSortable : '',
                    ].join(' ')}
                    onClick={col.sortable && col.key ? (e) => handleOrdenar(col.key, e) : undefined}
                    title={col.sortable && col.key ? 'Click: ordenar · Shift/Ctrl+Click: orden secundario' : undefined}
                  >
                    <span className={styles.thInner}>
                      <span>{col.label}</span>
                      {col.sortable && col.key && (
                        <span className={styles.sortIndicator}>
                          {numOrden != null && <span className={styles.sortBadge}>{numOrden}</span>}
                          <span className={styles.sortIcon}>
                            {getIconoOrden(col.key) === '▲'
                              ? <ArrowUp size={11} aria-hidden="true" />
                              : getIconoOrden(col.key) === '▼'
                                ? <ArrowDown size={11} aria-hidden="true" />
                                : <ArrowDown size={11} className={styles.sortIconDim} aria-hidden="true" />
                            }
                          </span>
                        </span>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className={styles.tbody}>
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={styles.stateBox}>
                    <div className={styles.spinner} />
                    <span>Cargando ranking…</span>
                  </div>
                </td>
              </tr>
            )}
            {error && !loading && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={`${styles.stateBox} ${styles.stateError}`}>
                    <AlertCircle size={20} aria-hidden="true" />
                    <span>{error}</span>
                  </div>
                </td>
              </tr>
            )}
            {!loading && !error && items.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={styles.stateBox}>
                    <PackageSearch size={32} aria-hidden="true" />
                    <span>No hay productos con los filtros seleccionados.</span>
                  </div>
                </td>
              </tr>
            )}
            {items.map((item) => (
              <tr key={item.item_id} className={`${styles.tr} ${loading ? styles.trLoading : ''}`}>
                <td className={`${styles.td} ${styles.tdCode} ${styles.tdSticky}`}>
                  {item.codigo ?? '—'}
                </td>
                <td className={`${styles.td} ${styles.tdDesc}`}>{item.descripcion ?? '—'}</td>
                <td className={styles.td}>{item.marca ?? '—'}</td>
                <td className={styles.td}>{item.categoria ?? '—'}</td>
                <td className={styles.td}>
                  {item.pm ?? <span className={styles.sinPm}>Sin PM</span>}
                </td>
                <td className={`${styles.td} ${styles.tdRight}`}>
                  <DiasGauge dias={item.dias_sin_venta} />
                </td>
                <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>
                  {item.erp_ageing_dias != null ? item.erp_ageing_dias : '—'}
                </td>
                <td className={styles.td}>
                  <span className={styles.dateCell}>
                    <span>{formatDate(item.last_purchase_date)}</span>
                    {item.last_purchase_qty != null && (
                      <span className={styles.dateQty}>×{item.last_purchase_qty}</span>
                    )}
                  </span>
                </td>
                <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>
                  {item.total_stock ?? 0}
                </td>
                <td className={`${styles.td} ${styles.tdRight}`}>
                  <CostCell valorCostoArs={item.valor_costo_ars} valorCostoUsd={item.valor_costo_usd} />
                </td>
                <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>
                  {formatARS(item.valor_venta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      {total > 0 && (
        <div className={styles.pagination}>
          <div className={styles.pageSizeWrap}>
            <label className={styles.pageSizeLabel} htmlFor="cr-page-size">Items por página</label>
            <select
              id="cr-page-size"
              className={styles.pageSizeSelect}
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              aria-label="Items por página"
            >
              {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>

          <span className={styles.paginationInfo}>
            {startRow.toLocaleString('es-AR')}–{endRow.toLocaleString('es-AR')} de {total.toLocaleString('es-AR')}
          </span>

          <div className={styles.paginationControls}>
            <button className={styles.pageBtn} onClick={() => goToPage(1)} disabled={page === 1} aria-label="Primera página">
              <ChevronsLeft size={15} />
            </button>
            <button className={styles.pageBtn} onClick={() => goToPage(page - 1)} disabled={page === 1} aria-label="Página anterior">
              <ChevronLeft size={15} />
            </button>
            {/* Numbered pages — show up to 5 around current */}
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              const offset = Math.max(0, Math.min(page - 3, totalPages - 5));
              const p = i + 1 + offset;
              return (
                <button
                  key={p}
                  className={`${styles.pageBtn} ${p === page ? styles.pageBtnActive : ''}`}
                  onClick={() => goToPage(p)}
                  aria-label={`Página ${p}`}
                  aria-current={p === page ? 'page' : undefined}
                >
                  {p}
                </button>
              );
            })}
            <button className={styles.pageBtn} onClick={() => goToPage(page + 1)} disabled={page >= totalPages} aria-label="Página siguiente">
              <ChevronRight size={15} />
            </button>
            <button className={styles.pageBtn} onClick={() => goToPage(totalPages)} disabled={page >= totalPages} aria-label="Última página">
              <ChevronsRight size={15} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Resumen table
// ---------------------------------------------------------------------------

function ResumenTable({ groupBy, onGroupByChange, data, loading, error }) {
  const showPm = groupBy === 'marca';

  return (
    <div className={styles.resumenWrap}>
      {/* Group-by toggle */}
      <div className={styles.resumenHeader}>
        <span className={styles.resumenLabel}>Agrupar por</span>
        <SegmentedControl
          options={[{ label: 'Marca', value: 'marca' }, { label: 'PM', value: 'pm' }]}
          value={groupBy}
          onChange={onGroupByChange}
        />
      </div>

      {loading && (
        <div className={styles.stateBox}>
          <div className={styles.spinner} />
          <span>Cargando resumen…</span>
        </div>
      )}
      {error && !loading && (
        <div className={`${styles.stateBox} ${styles.stateError}`}>
          <AlertCircle size={20} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && data && (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead className={styles.thead}>
              <tr>
                <th className={styles.th}>{groupBy === 'marca' ? 'Marca' : 'PM'}</th>
                {showPm && <th className={styles.th}>PM</th>}
                <th className={`${styles.th} ${styles.thRight}`}># Productos</th>
                <th className={`${styles.th} ${styles.thRight}`}>Stock total</th>
                <th className={`${styles.th} ${styles.thRight}`}>Valor costo</th>
                <th className={`${styles.th} ${styles.thRight}`}>Valor venta</th>
              </tr>
            </thead>
            <tbody className={styles.tbody}>
              {data.items.map((row, idx) => (
                <tr key={idx} className={styles.tr}>
                  <td className={styles.td}>{row.grupo ?? '—'}</td>
                  {showPm && <td className={styles.td}>{row.pm ?? <span className={styles.sinPm}>—</span>}</td>}
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>{row.num_productos?.toLocaleString('es-AR') ?? '—'}</td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>{row.stock_total?.toLocaleString('es-AR') ?? '—'}</td>
                  <td className={`${styles.td} ${styles.tdRight}`}>
                    <CostCell valorCostoArs={row.valor_costo_ars} valorCostoUsd={row.valor_costo_usd} />
                  </td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono}`}>{formatARS(row.valor_venta)}</td>
                </tr>
              ))}
            </tbody>
            {data.totales && (
              <tfoot>
                <tr className={styles.resumenTotalRow}>
                  <td className={`${styles.td} ${styles.resumenTotalLabel}`}>{data.totales.grupo}</td>
                  {showPm && <td className={styles.td} />}
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono} ${styles.resumenTotalValue}`}>{data.totales.num_productos?.toLocaleString('es-AR') ?? '—'}</td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono} ${styles.resumenTotalValue}`}>{data.totales.stock_total?.toLocaleString('es-AR') ?? '—'}</td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.resumenTotalValue}`}>
                    <CostCell valorCostoArs={data.totales.valor_costo_ars} valorCostoUsd={data.totales.valor_costo_usd} />
                  </td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMono} ${styles.resumenTotalValue}`}>{formatARS(data.totales.valor_venta)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ConsultasRanking() {
  const { facets, facetsLoading } = useFacets();

  const [view, setView] = useState('detalle'); // 'detalle' | 'resumen'
  const [groupBy, setGroupBy] = useState('marca');

  const {
    items,
    total,
    loading,
    error,
    marca,
    setMarca,
    categoria,
    setCategoria,
    pm,
    setPm,
    q,
    setQ,
    storIds,
    setStorIds,
    incluirSinStock,
    setIncluirSinStock,
    incluirCombos,
    setIncluirCombos,
    ordenColumnas,
    handleOrdenar,
    getIconoOrden,
    getNumeroOrden,
    page,
    pageSize,
    setPageSize,
    totalPages,
    goToPage,
    refresh: refreshRanking,
  } = useConsultasRanking();

  const resumen = useResumen({
    enabled: view === 'resumen',
    marca, categoria, pm, storIds, incluirSinStock, incluirCombos, groupBy,
  });

  const kpis = useKpis({ marca, categoria, pm, storIds, incluirSinStock, incluirCombos, q });

  // Stock sync — refetches ranking + KPIs after a successful sync
  const handleSyncComplete = useCallback(() => {
    refreshRanking();
  }, [refreshRanking]);

  const stockSync = useStockSync({ onSyncComplete: handleSyncComplete });

  const toolbarProps = {
    facets, facetsLoading,
    marca, setMarca,
    categoria, setCategoria,
    pm, setPm,
    storIds, setStorIds,
    incluirSinStock, setIncluirSinStock,
    incluirCombos, setIncluirCombos,
    busqueda: q, setBusqueda: setQ,
  };

  return (
    <div className={styles.page}>
      {/* Page header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.title}>Ranking de Productos</h1>
          {total > 0 && !loading && (
            <span className={styles.countChip}>
              {total.toLocaleString('es-AR')} productos
            </span>
          )}
        </div>
        <div className={styles.headerRight}>
          <SegmentedControl
            options={[{ label: 'Detalle', value: 'detalle' }, { label: 'Resumen', value: 'resumen' }]}
            value={view}
            onChange={setView}
          />
        </div>
      </header>

      {/* Toolbar */}
      <Toolbar {...toolbarProps} />

      {/* Stock freshness + refresh button */}
      <StockRefreshBar
        lastUpdated={stockSync.lastUpdated}
        syncing={stockSync.syncing}
        syncMessage={stockSync.syncMessage}
        onRefresh={stockSync.triggerRefresh}
      />

      {/* KPI cards row — visible in both Detalle and Resumen views */}
      <KpiCards data={kpis.data} loading={kpis.loading} />

      {/* Content */}
      <div className={styles.content}>
        {view === 'detalle' ? (
          <DetalleTable
            items={items}
            total={total}
            loading={loading}
            error={error}
            ordenColumnas={ordenColumnas}
            handleOrdenar={handleOrdenar}
            getIconoOrden={getIconoOrden}
            getNumeroOrden={getNumeroOrden}
            page={page}
            pageSize={pageSize}
            totalPages={totalPages}
            goToPage={goToPage}
            onPageSizeChange={setPageSize}
          />
        ) : (
          <ResumenTable
            groupBy={groupBy}
            onGroupByChange={setGroupBy}
            data={resumen.data}
            loading={resumen.loading}
            error={resumen.error}
          />
        )}
      </div>
    </div>
  );
}
