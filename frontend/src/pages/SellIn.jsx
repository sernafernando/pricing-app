import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, RefreshCw, ShieldAlert } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { productosAPI } from '../services/api';
import { sellInAPI } from '../services/sellInAPI';
import DateRangeFilter from '../components/DateRangeFilter';
import SearchInput from '../components/SearchInput';
import { FacetChips, Pagination, SplitPanelLayout } from '../components/kit';
import SellInCreatePanel from '../components/sellIn/SellInCreatePanel';
import SellInDetailPanel from '../components/sellIn/SellInDetailPanel';
import SellInResumen from '../components/sellIn/SellInResumen';
import SellInTable from '../components/sellIn/SellInTable';
import { buildSellInParams } from '../components/sellIn/sellInFormat';
import styles from './SellIn.module.css';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const APLICA_LABELS = { si: 'Aplican', no: 'No aplican' };
const EMPTY_FILTERS = { aplica: 'si', q: '', marcas: [], moneda: '', estado: '', desde: '', hasta: '', filtro: '' };

/** The brand list Productos and Publicaciones ML filter by (`GET /marcas`); empty on failure. */
function useMarcas(enabled) {
  const [marcas, setMarcas] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    productosAPI
      .marcas()
      .then((response) => active && setMarcas(response.data?.marcas ?? []))
      .catch(() => active && setMarcas([]));
    return () => {
      active = false;
    };
  }, [enabled]);
  return marcas;
}

/**
 * Sell in: purchase discounts that lower the cost of that purchase's units
 * (feature sell-in-sell-out T3). Lists the sell-in purchases with their
 * summary; `sell_in.ver` reads, `sell_in.gestionar` loads and voids.
 */
export default function SellIn() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('sell_in.ver');
  const puedeGestionar = tienePermiso('sell_in.gestionar');
  const marcas = useMarcas(puedeVer);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [lista, setLista] = useState(null);
  const [resumen, setResumen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);
  // The side panel: `{ tipo: 'crear' }` or `{ tipo: 'detalle', id }`; null when closed.
  const [panel, setPanel] = useState(null);
  const cerrarPanel = useCallback(() => setPanel(null), []);

  const params = useMemo(() => buildSellInParams({ ...filters, aplica: filters.aplica || 'todas' }), [filters]);

  const cargar = useCallback(async () => {
    if (!puedeVer) return;
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const [listResponse, resumenResponse] = await Promise.all([
        sellInAPI.listar({ ...params, page: Math.floor(offset / pageSize) + 1, page_size: pageSize }),
        sellInAPI.resumen(params),
      ]);
      if (requestId !== requestRef.current) return;
      setLista(listResponse.data);
      setResumen(resumenResponse.data);
    } catch (err) {
      if (requestId !== requestRef.current) return;
      setError(err?.response?.status === 403 ? 'No tenés permiso para ver sell in.' : 'No se pudieron cargar los sell in.');
      setLista(null);
      setResumen(null);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [puedeVer, params, offset, pageSize]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Changing what is filtered goes back to page 1.
  const setFilter = (patch) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setOffset(0);
  };

  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver sell in.
        </div>
      </div>
    );
  }

  const conteo = resumen?.conteo;

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Sell in</h1>
          <p className={styles.description}>Descuentos de compra que bajan el costo de las unidades de esa compra.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className="btn-tesla outline sm" onClick={cargar} disabled={loading}>
            <RefreshCw size={14} /> Actualizar
          </button>
          {puedeGestionar && (
            <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ tipo: 'crear' })}>
              <Plus size={14} /> Nuevo sell in
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {error}
        </div>
      )}

      <SplitPanelLayout
        open={Boolean(panel)}
        onClose={cerrarPanel}
        width="lg"
        ariaLabel={panel?.tipo === 'crear' ? 'Nuevo sell in' : 'Detalle del sell in'}
        panel={
          panel?.tipo === 'crear' ? (
            <SellInCreatePanel
              onClose={cerrarPanel}
              onCreated={(compra) => {
                setPanel({ tipo: 'detalle', id: compra.id });
                cargar();
              }}
            />
          ) : panel ? (
            <SellInDetailPanel key={panel.id} compraId={panel.id} puedeGestionar={puedeGestionar} onChanged={cargar} onClose={cerrarPanel} />
          ) : null
        }
      >
        <section className={styles.filterCard} aria-label="Filtros">
          <div className={styles.filterBand}>
            <DateRangeFilter
              fechaDesde={filters.desde}
              fechaHasta={filters.hasta}
              filtroActivo={filters.filtro}
              onChange={({ desde, hasta, filtro }) => setFilter({ desde, hasta, filtro })}
            />
            {filters.desde && (
              <button type="button" className="btn-tesla ghost sm" onClick={() => setFilter({ desde: '', hasta: '', filtro: '' })}>
                Todas las fechas
              </button>
            )}
            <div className={styles.searchSlot}>
              <SearchInput
                value={filters.q}
                onChange={(q) => setFilter({ q })}
                debounce={400}
                placeholder="Buscar por descripción, proveedor o producto…"
              />
            </div>
          </div>
          <div className={styles.filterBand}>
            <label className={styles.selectField}>
              <span className={styles.filterLabel}>Marca</span>
              <select
                className={styles.select}
                value={filters.marcas[0] ?? ''}
                onChange={(e) => setFilter({ marcas: e.target.value ? [e.target.value] : [] })}
              >
                <option value="">Todas</option>
                {marcas.map((marca) => (
                  <option key={marca} value={marca}>
                    {marca}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.selectField}>
              <span className={styles.filterLabel}>Moneda</span>
              <select className={styles.select} value={filters.moneda} onChange={(e) => setFilter({ moneda: e.target.value })}>
                <option value="">Todas</option>
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </label>
            <label className={styles.selectField}>
              <span className={styles.filterLabel}>Estado</span>
              <select className={styles.select} value={filters.estado} onChange={(e) => setFilter({ estado: e.target.value })}>
                <option value="">Todos</option>
                <option value="activa">Activa</option>
                <option value="anulada">Anulada</option>
              </select>
            </label>
          </div>
        </section>

        <div className={styles.facetRow}>
          <span className={styles.filterLabel}>Aplicación:</span>
          <FacetChips
            label="Aplicación"
            options={['si', 'no']}
            labels={APLICA_LABELS}
            counts={conteo}
            total={conteo?.todas}
            activeValue={filters.aplica}
            onChange={(aplica) => setFilter({ aplica })}
          />
        </div>

        <SellInResumen resumen={resumen} />

        {loading && !lista ? (
          <p className={styles.loading}>Cargando sell in…</p>
        ) : (
          <SellInTable
            compras={lista?.items ?? []}
            selectedId={panel?.tipo === 'detalle' ? panel.id : null}
            onSelect={(id) => setPanel({ tipo: 'detalle', id })}
          />
        )}

        {lista && (
          <Pagination
            total={lista.total}
            offset={offset}
            pageSize={pageSize}
            onOffsetChange={setOffset}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setOffset(0);
            }}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            summary={<span>{lista.total} sell in</span>}
          />
        )}
      </SplitPanelLayout>
    </div>
  );
}
