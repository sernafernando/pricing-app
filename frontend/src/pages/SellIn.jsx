import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, RefreshCw, ShieldAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
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
import SellOutAnularMasivo from '../components/sellOut/SellOutAnularMasivo';
import styles from './SellIn.module.css';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const BONOS_PAGE_SIZES = [10, 25, 50];
const CAMPANAS_PAGE_SIZES = [10, 25, 50];
const PANEL_LABELS = { crear: 'Nuevo sell in', detalle: 'Detalle del sell in', bono: 'Bono de marca', campana: 'Campaña de sell out' };
const APLICA_LABELS = { si: 'Aplican', no: 'No aplican' };
const EMPTY_FILTERS = { aplica: 'si', q: '', marcas: [], moneda: '', estado: '', desde: '', hasta: '', filtro: '' };
const TIPO_LABELS = { compra: 'Por compra', bono: 'Bono de marca' };
// The two counts measure different lists: the bonus list takes none of the purchase filters.
const TIPO_HINTS = {
  compra: 'Los sell in por compra con los filtros de arriba',
  bono: 'Todos los bonos de marca cargados: los filtros de arriba no los cuentan',
};
// The active bonuses the summary cards add up.
// ponytail: brands and reached purchases count only the first 200 active bonuses; ask the backend for those totals if active bonuses ever pass 200
const BONOS_VIGENTES_MAX = 200;
const TAB_SELL_OUT = 'sell-out';

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

/**
 * The active brand bonuses for the summary cards (`GET /sell-in/bonos?estado=activa`):
 * how many, how many brands they cover and how many purchases they reached. Null until they answer,
 * `{ error: true }` when they could not be read.
 */
function useBonosVigentes(enabled) {
  const [resumen, setResumen] = useState(null);
  const requestRef = useRef(0);
  const recargar = useCallback(async () => {
    if (!enabled) return;
    const requestId = ++requestRef.current;
    try {
      const { data } = await sellInBonosAPI.listar({ estado: 'activa', page: 1, page_size: BONOS_VIGENTES_MAX });
      if (requestId !== requestRef.current) return;
      const items = data?.items ?? [];
      setResumen({
        vigentes: data?.total ?? items.length,
        marcas: new Set(items.map((bono) => bono.marca).filter(Boolean)).size,
        compras: items.reduce((sum, bono) => sum + (bono.compras_activas ?? 0), 0),
      });
    } catch {
      if (requestId === requestRef.current) setResumen({ error: true });
    }
  }, [enabled]);
  useEffect(() => {
    recargar();
  }, [recargar]);
  return { resumen, recargar };
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
 * Sell in / Sell out (Stitch `01-sellin-lista-aplican`, `04-sellout-no-aplican`):
 * one page, two tabs. Sell in holds the purchase discounts that lower the cost
 * of that purchase's units and the brand bonuses; Sell out holds the campaigns.
 * The selected tab lives in the URL (`?tab=sell-out`) so a reload keeps it.
 * `sell_in.ver` reads the page, `sell_out.ver` shows the Sell out tab.
 */
export default function SellIn() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('sell_in.ver');
  const puedeGestionar = tienePermiso('sell_in.gestionar');
  const marcas = useMarcas(puedeVer);
  const bonos = useBonos(puedeVer);
  const bonosVigentes = useBonosVigentes(puedeVer);
  const puedeVerSellOut = tienePermiso('sell_out.ver');
  const campanas = useCampanas(puedeVer && puedeVerSellOut);
  const puedeGestionarSellOut = puedeVerSellOut && tienePermiso('sell_out.gestionar');
  const gruposOffset = useGruposOffset(puedeVer && puedeGestionarSellOut);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = puedeVerSellOut && searchParams.get('tab') === TAB_SELL_OUT ? TAB_SELL_OUT : 'sell-in';
  const [tipo, setTipo] = useState('');
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
  // Arrow keys move between the tabs (WAI-ARIA tabs pattern, automatic activation).
  const tabsVisibles = puedeVerSellOut ? ['sell-in', TAB_SELL_OUT] : ['sell-in'];
  const onTabsKeyDown = (event) => {
    const actual = tabsVisibles.indexOf(tab);
    const destino = {
      ArrowRight: (actual + 1) % tabsVisibles.length,
      ArrowLeft: (actual - 1 + tabsVisibles.length) % tabsVisibles.length,
      Home: 0,
      End: tabsVisibles.length - 1,
    }[event.key];
    if (destino === undefined) return;
    event.preventDefault();
    const next = tabsVisibles[destino];
    cambiarTab(next);
    document.getElementById(`${next}-tab`)?.focus();
  };
  const cambiarTab = (next) => {
    if (next === tab) return;
    setPanel(null);
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === TAB_SELL_OUT) params.set('tab', TAB_SELL_OUT);
        else params.delete('tab');
        return params;
      },
      { replace: true },
    );
  };

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
  const enSellOut = tab === TAB_SELL_OUT;
  const totalCompras = lista?.total;
  const totalBonos = bonos.lista?.total;
  const tipoTotal = totalCompras === undefined || totalBonos === undefined ? undefined : totalCompras + totalBonos;
  const verCompras = tipo !== 'bono';
  const verBonos = tipo !== 'compra';

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Sell in / Sell out</h1>
          <p className={styles.description}>Sell in baja el costo de la compra; sell out suma ganancia por campaña.</p>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              cargar();
              bonos.recargar();
              bonosVigentes.recargar();
              campanas.recargar();
            }}
            disabled={loading}
          >
            <RefreshCw size={14} /> Actualizar
          </button>
          {!enSellOut && puedeGestionar && (
            <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ tipo: 'crear' })}>
              <Plus size={14} /> Nuevo sell in
            </button>
          )}
          {enSellOut && puedeGestionarSellOut && (
            <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ tipo: 'campana', id: null })}>
              <Plus size={14} /> Nueva campaña
            </button>
          )}
        </div>
      </header>

      <div className={styles.tabs} role="tablist" aria-label="Sell in / Sell out" onKeyDown={onTabsKeyDown}>
        <button
          type="button"
          role="tab"
          id="sell-in-tab"
          aria-selected={!enSellOut}
          aria-controls={!enSellOut ? 'sell-in-panel' : undefined}
          tabIndex={!enSellOut ? 0 : -1}
          className={`${styles.tab} ${!enSellOut ? styles.tabActive : ''}`}
          onClick={() => cambiarTab('sell-in')}
        >
          <span>Sell in</span> <span className={styles.srOnly}>·</span>{' '}
          <span className={styles.tabCount}>{conteo ? conteo.todas.toLocaleString('es-AR') : error ? '—' : '…'}</span>
        </button>
        {puedeVerSellOut && (
          <button
            type="button"
            role="tab"
            id="sell-out-tab"
            aria-selected={enSellOut}
            aria-controls={enSellOut ? 'sell-out-panel' : undefined}
            tabIndex={enSellOut ? 0 : -1}
            className={`${styles.tab} ${enSellOut ? styles.tabActive : ''}`}
            onClick={() => cambiarTab(TAB_SELL_OUT)}
          >
            <span>Sell out</span> <span className={styles.srOnly}>·</span>{' '}
            <span className={styles.tabCount}>{campanas.lista ? campanas.lista.total.toLocaleString('es-AR') : campanas.error ? '—' : '…'}</span>
          </button>
        )}
      </div>

      {error && !enSellOut && (
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
                bonosVigentes.recargar();
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
                bonosVigentes.recargar();
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
              onChanged={() => {
                cargar();
                bonosVigentes.recargar();
              }}
              onVerBono={verBono}
              onClose={cerrarPanel}
            />
          ) : null
        }
      >
        {!enSellOut ? (
          <div role="tabpanel" id="sell-in-panel" aria-labelledby="sell-in-tab">
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
              <div className={styles.filterBand}>
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
                    allLast
                  />
                </div>
                <div className={styles.facetRow}>
                  <span className={styles.filterLabel}>Tipo:</span>
                  <FacetChips
                    label="Tipo"
                    allLabel="Todos"
                    options={['compra', 'bono']}
                    labels={TIPO_LABELS}
                    hints={TIPO_HINTS}
                    counts={{ compra: totalCompras, bono: totalBonos }}
                    total={tipoTotal}
                    activeValue={tipo}
                    onChange={setTipo}
                    allLast
                  />
                </div>
              </div>
            </section>

            <SellInResumen resumen={resumen} bonos={bonosVigentes.resumen} />

            {verCompras && (
              <>
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
              </>
            )}

            {verBonos && (
              <section className={styles.bonos} aria-labelledby="sell-in-bonos-titulo">
                <h2 id="sell-in-bonos-titulo" className={styles.sectionTitle}>
                  Bonos de marca
                </h2>
                <p className={styles.description}>
                  Un monto por unidad facturada de una marca, en un rango de fechas de factura. Se aplica solo a cada compra que alcanza.
                </p>
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
            )}
          </div>
        ) : (
          <div role="tabpanel" id="sell-out-panel" aria-labelledby="sell-out-tab">
            <section className={styles.sellOut} aria-labelledby="sell-out-campanas-titulo">
              {/* The tab already names the list (Stitch 04 has no section title): the heading only names the region. */}
              <h2 id="sell-out-campanas-titulo" className={styles.srOnly}>
                Campañas de sell out
              </h2>
              <section className={styles.filterCard} aria-label="Filtros de campañas">
                <div className={styles.filterBand}>
                  <div className={styles.searchSlot}>
                    <SearchInput value={campanas.q} onChange={campanas.buscar} debounce={400} placeholder="Buscar campaña por nombre…" />
                  </div>
                </div>
              </section>
              {campanas.error && (
                <div className={styles.errorBar} role="alert">
                  <ShieldAlert size={16} /> {campanas.error}
                </div>
              )}
              {campanas.lista && (
                <>
                  <SellOutAnularMasivo
                    key={campanas.q.trim()}
                    campanas={campanas.lista.items}
                    total={campanas.lista.total}
                    filtros={campanas.q.trim() ? { q: campanas.q.trim() } : {}}
                    puedeGestionar={puedeGestionarSellOut}
                    selectedId={panel?.tipo === 'campana' ? panel.id : null}
                    onSelect={verCampana}
                    onAnuladas={campanas.recargar}
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
          </div>
        )}
      </SplitPanelLayout>
    </div>
  );
}
