import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, RefreshCw, ShieldAlert } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { productosAPI } from '../services/api';
import { sellInAPI, sellInBonosAPI } from '../services/sellInAPI';
import { sellOutAPI } from '../services/sellOutAPI';
import DateRangeFilter from '../components/DateRangeFilter';
import SearchInput from '../components/SearchInput';
import { FacetChips, Pagination, SplitPanelLayout } from '../components/kit';
import SellInBonoPanel from '../components/sellIn/SellInBonoPanel';
import SellInBonosTable from '../components/sellIn/SellInBonosTable';
import SellInDetailPanel from '../components/sellIn/SellInDetailPanel';
import SellInNuevoPanel from '../components/sellIn/SellInNuevoPanel';
import SellInResumen from '../components/sellIn/SellInResumen';
import SellInTable from '../components/sellIn/SellInTable';
import { buildSellInParams } from '../components/sellIn/sellInFormat';
import SellOutCampanaPanel from '../components/sellOut/SellOutCampanaPanel';
import SellOutCampanasTable from '../components/sellOut/SellOutCampanasTable';
import styles from './SellIn.module.css';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const BONOS_PAGE_SIZES = [10, 25, 50];
const CAMPANAS_PAGE_SIZES = [10, 25, 50];
const PANEL_LABELS = { crear: 'Nuevo sell in', detalle: 'Detalle del sell in', bono: 'Bono de marca', campana: 'Campaña de sell out' };
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

/** The brand bonuses page by page (`GET /sell-in/bonos`, newest first); `recargar` asks again. */
function useBonos(enabled) {
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(BONOS_PAGE_SIZES[0]);
  const [lista, setLista] = useState(null);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);
  const recargar = useCallback(async () => {
    if (!enabled) return;
    const requestId = ++requestRef.current;
    setError(null);
    try {
      const { data } = await sellInBonosAPI.listar({ page: Math.floor(offset / pageSize) + 1, page_size: pageSize });
      if (requestId === requestRef.current) setLista(data);
    } catch {
      if (requestId === requestRef.current) setError('No se pudieron cargar los bonos de marca.');
    }
  }, [enabled, offset, pageSize]);
  useEffect(() => {
    recargar();
  }, [recargar]);
  return { lista, error, offset, setOffset, pageSize, setPageSize, recargar };
}

/** The offset groups a sell-out campaign can reach (`GET /offset-grupos`); empty on failure. */
function useGruposOffset(enabled) {
  const [grupos, setGrupos] = useState([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    sellOutAPI
      .grupos()
      .then(({ data }) => active && setGrupos(data ?? []))
      .catch(() => active && setGrupos([]));
    return () => {
      active = false;
    };
  }, [enabled]);
  return grupos;
}

/** The sell-out campaigns page by page (`GET /sell-out/campanas`), searched by name (`q`); `recargar` asks again. */
function useCampanas(enabled) {
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(CAMPANAS_PAGE_SIZES[0]);
  const [lista, setLista] = useState(null);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);
  const recargar = useCallback(async () => {
    if (!enabled) return;
    const requestId = ++requestRef.current;
    setError(null);
    const params = { page: Math.floor(offset / pageSize) + 1, page_size: pageSize };
    try {
      const { data } = await sellOutAPI.listar(q.trim() ? { q: q.trim(), ...params } : params);
      if (requestId === requestRef.current) setLista(data);
    } catch {
      if (requestId === requestRef.current) setError('No se pudieron cargar las campañas de sell out.');
    }
  }, [enabled, q, offset, pageSize]);
  useEffect(() => {
    recargar();
  }, [recargar]);
  const buscar = useCallback((value) => {
    setQ(value);
    setOffset(0);
  }, []);
  return { lista, error, q, buscar, offset, setOffset, pageSize, setPageSize, recargar };
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
  const bonos = useBonos(puedeVer);
  const puedeVerSellOut = tienePermiso('sell_out.ver');
  const campanas = useCampanas(puedeVer && puedeVerSellOut);
  const puedeGestionarSellOut = puedeVerSellOut && tienePermiso('sell_out.gestionar');
  const gruposOffset = useGruposOffset(puedeVer && puedeGestionarSellOut);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [lista, setLista] = useState(null);
  const [resumen, setResumen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);
  // The side panel: `{ tipo: 'crear' }`, `{ tipo: 'detalle', id }` (a purchase) or `{ tipo: 'bono', id }`; null when closed.
  const [panel, setPanel] = useState(null);
  const cerrarPanel = useCallback(() => setPanel(null), []);
  const verBono = useCallback((id) => setPanel({ tipo: 'bono', id }), []);
  const verCompra = useCallback((id) => setPanel({ tipo: 'detalle', id }), []);
  const verCampana = useCallback((id) => setPanel({ tipo: 'campana', id }), []);

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
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              cargar();
              bonos.recargar();
              campanas.recargar();
            }}
            disabled={loading}
          >
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
        ariaLabel={PANEL_LABELS[panel?.tipo] ?? 'Detalle del sell in'}
        panel={
          panel?.tipo === 'crear' ? (
            <SellInNuevoPanel
              marcas={marcas}
              onClose={cerrarPanel}
              onCreated={(compra) => {
                setPanel({ tipo: 'detalle', id: compra.id });
                cargar();
              }}
              onBonoCreado={(bono) => {
                verBono(bono.id);
                bonos.recargar();
              }}
            />
          ) : panel?.tipo === 'bono' ? (
            <SellInBonoPanel
              key={`bono-${panel.id}`}
              bonoId={panel.id}
              marcas={marcas}
              puedeGestionar={puedeGestionar}
              onSaved={() => {
                bonos.recargar();
                cargar();
              }}
              onVerCompra={verCompra}
              onClose={cerrarPanel}
            />
          ) : panel?.tipo === 'campana' ? (
            <SellOutCampanaPanel
              key={`campana-${panel.id ?? 'nueva'}`}
              campanaId={panel.id}
              grupos={gruposOffset}
              puedeGestionar={puedeGestionarSellOut}
              onSaved={(campana) => {
                if (panel.id === null) verCampana(campana.id);
                campanas.recargar();
              }}
              onClose={cerrarPanel}
            />
          ) : panel ? (
            <SellInDetailPanel
              key={panel.id}
              compraId={panel.id}
              puedeGestionar={puedeGestionar}
              onChanged={cargar}
              onVerBono={verBono}
              onClose={cerrarPanel}
            />
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
            onSelect={verCompra}
            onVerBono={verBono}
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

        <section className={styles.bonos} aria-labelledby="sell-in-bonos-titulo">
          <h2 id="sell-in-bonos-titulo" className={styles.sectionTitle}>
            Bonos de marca
          </h2>
          <p className={styles.description}>Un monto por unidad facturada de una marca, en un rango de fechas de factura. Se aplica solo a cada compra que alcanza.</p>
          {bonos.error && (
            <div className={styles.errorBar} role="alert">
              <ShieldAlert size={16} /> {bonos.error}
            </div>
          )}
          {bonos.lista && (
            <>
              <SellInBonosTable bonos={bonos.lista.items} selectedId={panel?.tipo === 'bono' ? panel.id : null} onSelect={verBono} />
              <Pagination
                total={bonos.lista.total}
                offset={bonos.offset}
                pageSize={bonos.pageSize}
                onOffsetChange={bonos.setOffset}
                onPageSizeChange={(size) => {
                  bonos.setPageSize(size);
                  bonos.setOffset(0);
                }}
                pageSizeOptions={BONOS_PAGE_SIZES}
                summary={<span>{bonos.lista.total} bonos</span>}
              />
            </>
          )}
        </section>

        {puedeVerSellOut && (
          <section className={styles.bonos} aria-labelledby="sell-out-campanas-titulo">
            <div className={styles.sectionHead}>
              <h2 id="sell-out-campanas-titulo" className={styles.sectionTitle}>
                Campañas de sell out
              </h2>
              {puedeGestionarSellOut && (
                <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ tipo: 'campana', id: null })}>
                  <Plus size={14} /> Nueva campaña
                </button>
              )}
            </div>
            <p className={styles.description}>
              Un monto por unidad o un porcentaje que la marca reconoce por cada venta de los productos alcanzados, en un rango de fechas.
            </p>
            <div className={styles.searchSlot}>
              <SearchInput value={campanas.q} onChange={campanas.buscar} debounce={400} placeholder="Buscar campaña por nombre…" />
            </div>
            {campanas.error && (
              <div className={styles.errorBar} role="alert">
                <ShieldAlert size={16} /> {campanas.error}
              </div>
            )}
            {campanas.lista && (
              <>
                <SellOutCampanasTable
                  campanas={campanas.lista.items}
                  selectedId={panel?.tipo === 'campana' ? panel.id : null}
                  onSelect={verCampana}
                />
                <Pagination
                  total={campanas.lista.total}
                  offset={campanas.offset}
                  pageSize={campanas.pageSize}
                  onOffsetChange={campanas.setOffset}
                  onPageSizeChange={(size) => {
                    campanas.setPageSize(size);
                    campanas.setOffset(0);
                  }}
                  pageSizeOptions={CAMPANAS_PAGE_SIZES}
                  summary={<span>{campanas.lista.total} campañas</span>}
                />
              </>
            )}
          </section>
        )}
      </SplitPanelLayout>
    </div>
  );
}
