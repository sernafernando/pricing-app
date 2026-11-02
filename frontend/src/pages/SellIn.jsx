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
import SellInAnularMasivo from '../components/sellIn/SellInAnularMasivo';
import SellInBonoPanel from '../components/sellIn/SellInBonoPanel';
import SellInBonosTable from '../components/sellIn/SellInBonosTable';
import SellInDetailPanel from '../components/sellIn/SellInDetailPanel';
import SellInNuevoPanel from '../components/sellIn/SellInNuevoPanel';
import SellInResumen from '../components/sellIn/SellInResumen';
import SellInTable from '../components/sellIn/SellInTable';
import { resolverIdsFiltrados } from '../components/sellIn/sellInAnularMasivo';
import { buildSellInParams } from '../components/sellIn/sellInFormat';
import { useSeleccionMasiva } from '../components/sellIn/useSeleccionMasiva';
import SellOutCampanaPanel from '../components/sellOut/SellOutCampanaPanel';
import SellOutAnularMasivo from '../components/sellOut/SellOutAnularMasivo';
import GruposTab from '../components/grupos/GruposTab';
import styles from './SellIn.module.css';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const BONOS_PAGE_SIZES = [10, 25, 50];
const CAMPANAS_PAGE_SIZES = [10, 25, 50];
const COMPRAS = { singular: 'compra', plural: 'compras' };
const BONOS = { singular: 'bono', plural: 'bonos' };
const REVIERTE_COMPRAS = 'Se liberan sus unidades: las ventas que tomaban pasan a las compras siguientes. Las compras que genera un bono de marca no se anulan acá.';
/** Why "todo lo filtrado" leaves some purchases out: "N anulables; M generadas por bonos no se pueden anular a mano." */
function notaGeneradas(anulables, generadas) {
  if (!generadas) return null;
  const a = anulables === 1 ? '1 anulable' : `${anulables} anulables`;
  const g = generadas === 1 ? '1 generada por bonos no se puede anular a mano' : `${generadas} generadas por bonos no se pueden anular a mano`;
  return `${a}; ${g}.`;
}

const REVIERTE_BONOS = 'Después se anulan las compras que generó cada bono, y un bono sobre el costo deja de aplicarse a sus ventas.';
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
const TAB_GRUPOS = 'grupos';

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

/**
 * The offset groups a sell-out campaign can reach (`GET /offset-grupos`); empty on failure. A new `version`
 * ("Actualizar", or a group created, changed or deleted in the Grupos tab) asks them again.
 */
function useGruposOffset(enabled, version) {
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
  }, [enabled, version]);
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
  // Always the current search and page: a callback kept by a request in flight (a bulk void) calls it later.
  const recargarRef = useRef(recargar);
  useEffect(() => {
    recargarRef.current = recargar;
  }, [recargar]);
  const recargarActual = useCallback(() => recargarRef.current(), []);
  return { lista, error, q, buscar, offset, setOffset, pageSize, setPageSize, recargar, recargarActual };
}

/**
 * Sell in / Sell out (Stitch `01-sellin-lista-aplican`, `04-sellout-no-aplican`):
 * one page, two tabs. Sell in holds the purchase discounts that lower the cost
 * of that purchase's units and the brand bonuses; Sell out holds the campaigns.
 * The selected tab lives in the URL (`?tab=sell-out`) so a reload keeps it.
 * `sell_in.ver` reads the page, `sell_out.ver` shows the Sell out tab, `config.editar_constantes` (the offset
 * groups API permission) the Grupos tab (`?tab=grupos`).
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
  const [searchParams, setSearchParams] = useSearchParams();
  const puedeGestionarGrupos = tienePermiso('config.editar_constantes');
  // "Actualizar" bumps it: the Grupos tab asks its groups again.
  const [versionGrupos, setVersionGrupos] = useState(0);
  // A group created, changed or deleted in the Grupos tab: the campaign form's groups are asked again.
  const [cambiosGrupos, setCambiosGrupos] = useState(0);
  const gruposOffset = useGruposOffset(puedeVer && puedeGestionarSellOut, versionGrupos + cambiosGrupos);
  const tabsVisibles = ['sell-in', ...(puedeVerSellOut ? [TAB_SELL_OUT] : []), ...(puedeGestionarGrupos ? [TAB_GRUPOS] : [])];
  const tabUrl = searchParams.get('tab');
  const tab = tabsVisibles.includes(tabUrl) ? tabUrl : 'sell-in';
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
  // The bulk void (`sell_in.gestionar`): the checked purchases and bonuses, and what the last one did.
  const selCompras = useSeleccionMasiva();
  const selBonos = useSeleccionMasiva();
  const [aviso, setAviso] = useState(null);
  // Arrow keys move between the tabs (WAI-ARIA tabs pattern, automatic activation).
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
        if (next === 'sell-in') params.delete('tab');
        else params.set('tab', next);
        return params;
      },
      { replace: true },
    );
  };

  const params = useMemo(() => buildSellInParams({ ...filters, aplica: filters.aplica || 'todas' }), [filters]);
  const paramsRef = useRef(params);
  useEffect(() => {
    paramsRef.current = params;
  }, [params]);

  // "Todo lo filtrado" of the purchases, dropped when the filters changed while it was being read.
  const seleccionarComprasFiltradas = async () => {
    const desde = params;
    const ids = await resolverIdsFiltrados(sellInAPI.listar, desde, { total: lista.total, generadas: lista.generadas ?? 0, filtrosActivos: true });
    if (paramsRef.current !== desde) throw new Error('Los filtros cambiaron mientras se seleccionaba. Volvé a intentarlo.');
    selCompras.reemplazar(ids);
  };

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

  // Other filters are another set: what was checked under the previous ones is dropped.
  const limpiarCompras = selCompras.limpiar;
  useEffect(() => {
    limpiarCompras();
  }, [params, limpiarCompras]);

  // After a bulk void: the side panel of a record it voided closes (it read the record when it opened). What it voided
  // leaves the list, so the page it was on may no longer exist: each list goes back to page 1. The void can take a
  // while and the page stays usable, so the reload reads the page and filters on screen when it ends (refs).
  const recargarComprasRef = useRef(null);
  const recargarBonosRef = useRef(null);
  const { offset: bonosOffset, setOffset: setBonosOffset, recargar: recargarBonos } = bonos;
  const recargarVigentes = bonosVigentes.recargar;
  useEffect(() => {
    recargarComprasRef.current = () => {
      if (offset === 0) cargar();
      else setOffset(0);
      recargarVigentes();
    };
    recargarBonosRef.current = () => {
      if (bonosOffset === 0) recargarBonos();
      else setBonosOffset(0);
      recargarVigentes();
      cargar();
    };
  }, [offset, cargar, bonosOffset, setBonosOffset, recargarBonos, recargarVigentes]);
  const anuladoMasivo = (seleccion, tipoPanel, recargarRef) => (mensaje, { anuladas }) => {
    seleccion.limpiar();
    setAviso(mensaje);
    setPanel((actual) => (actual?.tipo === tipoPanel && anuladas.includes(actual.id) ? null : actual));
    recargarRef.current();
  };

  // The last result stays until the filters change or the next selection starts.
  const haySeleccion = selCompras.ids.size > 0 || selBonos.ids.size > 0;
  useEffect(() => {
    if (haySeleccion) setAviso(null);
  }, [haySeleccion]);
  useEffect(() => {
    setAviso(null);
  }, [params]);

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
  const enSellIn = tab === 'sell-in';
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
              setVersionGrupos((v) => v + 1);
            }}
            disabled={loading}
          >
            <RefreshCw size={14} /> Actualizar
          </button>
          {enSellIn && puedeGestionar && (
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
          aria-selected={enSellIn}
          aria-controls={enSellIn ? 'sell-in-panel' : undefined}
          tabIndex={enSellIn ? 0 : -1}
          className={`${styles.tab} ${enSellIn ? styles.tabActive : ''}`}
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
        {puedeGestionarGrupos && (
          <button
            type="button"
            role="tab"
            id="grupos-tab"
            aria-selected={tab === TAB_GRUPOS}
            aria-controls={tab === TAB_GRUPOS ? 'grupos-panel' : undefined}
            tabIndex={tab === TAB_GRUPOS ? 0 : -1}
            className={`${styles.tab} ${tab === TAB_GRUPOS ? styles.tabActive : ''}`}
            onClick={() => cambiarTab(TAB_GRUPOS)}
          >
            Grupos
          </button>
        )}
      </div>

      {error && enSellIn && (
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
              key={`campana-${panel.id ?? 'nueva'}-${panel.version ?? 0}`}
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
        {tab === TAB_GRUPOS ? (
          <div role="tabpanel" id="grupos-panel" aria-labelledby="grupos-tab">
            <GruposTab version={versionGrupos} onGruposCambiados={() => setCambiosGrupos((v) => v + 1)} />
          </div>
        ) : enSellIn ? (
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

            {aviso && (
              <p role="status" className={styles.loading}>
                {aviso}
              </p>
            )}

            {verCompras && (
              <>
                {puedeGestionar && lista && (
                  <SellInAnularMasivo
                    sustantivo={COMPRAS}
                    seleccionados={[...selCompras.ids]}
                    total={lista.total - (lista.generadas ?? 0)}
                    nota={notaGeneradas(lista.total - (lista.generadas ?? 0), lista.generadas ?? 0)}
                    revierte={REVIERTE_COMPRAS}
                    onSeleccionarFiltrado={seleccionarComprasFiltradas}
                    onLimpiar={selCompras.limpiar}
                    anular={sellInAPI.anularMasivo}
                    onHecho={anuladoMasivo(selCompras, 'detalle', recargarComprasRef)}
                  />
                )}
                {loading && !lista ? (
                  <p className={styles.loading}>Cargando sell in…</p>
                ) : (
                  <SellInTable
                    compras={lista?.items ?? []}
                    selectedId={panel?.tipo === 'detalle' ? panel.id : null}
                    onSelect={verCompra}
                    onVerBono={verBono}
                    {...(puedeGestionar && { seleccion: selCompras.ids, onToggle: selCompras.toggle, onTogglePagina: selCompras.togglePagina })}
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
                    {puedeGestionar && (
                      <SellInAnularMasivo
                        sustantivo={BONOS}
                        seleccionados={[...selBonos.ids]}
                        total={bonos.lista.total}
                        revierte={REVIERTE_BONOS}
                        onSeleccionarFiltrado={async () =>
                          selBonos.reemplazar(await resolverIdsFiltrados(sellInBonosAPI.listar, {}, { total: bonos.lista.total, filtrosActivos: false }))
                        }
                        onLimpiar={selBonos.limpiar}
                        anular={sellInBonosAPI.anularMasivo}
                        onHecho={anuladoMasivo(selBonos, 'bono', recargarBonosRef)}
                      />
                    )}
                    <SellInBonosTable
                      bonos={bonos.lista.items}
                      selectedId={panel?.tipo === 'bono' ? panel.id : null}
                      onSelect={verBono}
                      {...(puedeGestionar && { seleccion: selBonos.ids, onToggle: selBonos.toggle, onTogglePagina: selBonos.togglePagina })}
                    />
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
                    onAnuladas={(ids) => {
                      campanas.recargarActual();
                      // The open campaign was just voided: read it again (a new key remounts the panel). Functional update:
                      // the panel may have been closed or changed while the request was in flight.
                      setPanel((actual) =>
                        actual?.tipo === 'campana' && ids.includes(actual.id)
                          ? { ...actual, version: (actual.version ?? 0) + 1 }
                          : actual,
                      );
                    }}
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
