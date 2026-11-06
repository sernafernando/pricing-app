import { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw, ShieldAlert } from 'lucide-react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { productosAPI } from '../services/api';
import { tacticalsAPI } from '../services/tacticalsAPI';
import { SplitPanelLayout } from '../components/kit';
import SellInBonoPanel from '../components/sellIn/SellInBonoPanel';
import SellInDetailPanel from '../components/sellIn/SellInDetailPanel';
import SellInProductoCostoPanel from '../components/sellIn/SellInProductoCostoPanel';
import SellInProductosCosto from '../components/sellIn/SellInProductosCosto';
import SellOutCampanaPanel from '../components/sellOut/SellOutCampanaPanel';
import GruposTab from '../components/grupos/GruposTab';
import TacticalsList from '../components/tacticals/TacticalsList';
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import { canViewProductPrices } from '../components/pricing/productPricePermissions';
import styles from './SellIn.module.css';

const TAB_TACTICALS = 'tacticals';
const TAB_GRUPOS = 'grupos';
const TAB_PRODUCTOS = 'productos';
/**
 * The tabs the page had before Tacticals took them over: their links open Tacticals with that Tipo. Programas is gone
 * too (owner, 2026-11-06: "si ahora todo es tactical"); its links open Tacticals with every Tipo.
 */
const TIPO_DE_TAB_VIEJA = { 'sell-in': 'sell_in', 'sell-out': 'sell_out', programas: 'todos' };
/** The panel a tactical line's record opens in, by the line's `origen`. */
const PANEL_DE_ORIGEN = { sell_out_campana: 'campana', sell_in_bono: 'bono', sell_in_compra: 'detalle' };
const PANEL_LABELS = { detalle: 'Detalle del sell in', bono: 'Bono de marca', campana: 'Campaña de sell out', producto: 'Costo de sell in' };

/**
 * The Tacticals tab's count: the current tacticals (`GET /tacticals`, one row asked); `error` on a failure (the tab
 * shows "—").
 */
function useConteoTacticals(enabled, version) {
  const [estado, setEstado] = useState({ total: null, error: false });
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    tacticalsAPI
      .listar({ estado: 'vigentes', page: 1, page_size: 1 })
      .then(({ data }) => active && setEstado({ total: data.total, error: false }))
      .catch(() => active && setEstado({ total: null, error: true }));
    return () => {
      active = false;
    };
  }, [enabled, version]);
  return estado;
}

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
 * Sell in / Sell out, one view (owner, 2026-11-05: "trae todo a tacticals"): the Tacticals tab holds the brands'
 * programs of both kinds, with "Nuevo tactical", each tactical's lines and, per line, its record read only ("Ver
 * ventas"). Grupos (`grupos.ver`) holds the product groups, where `config.editar_constantes` also creates, edits and
 * deletes. The tab lives in the URL (`?tab=grupos`); the old `?tab=sell-in` / `?tab=sell-out` / `?tab=programas` links
 * open Tacticals with that Tipo. `sell_in.ver` reads the page.
 */
export default function SellIn() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('sell_in.ver');
  const puedeVerGrupos = tienePermiso('grupos.ver');
  // Nuevo tactical asks only the kind's gestionar, so its button does too.
  const puedeCrearTactical = tienePermiso('sell_in.gestionar') || tienePermiso('sell_out.gestionar');
  const marcas = useMarcas(puedeVer);
  const [searchParams, setSearchParams] = useSearchParams();
  // "Actualizar" bumps it: every tab of the page asks its data again.
  const [versionPagina, setVersionPagina] = useState(0);
  // The Productos list (the lot viewer's permission plus sell_in.ver, like its endpoint); a mode change reads it again.
  const puedeVerProductos = puedeVer && canViewProductPrices(tienePermiso);
  const [versionProductos, setVersionProductos] = useState(0);
  const tacticals = useConteoTacticals(puedeVer, versionPagina);

  const tabUrl = searchParams.get('tab');
  // The Tipo an old link asked for, read once: the list keeps it after the URL is rewritten.
  const [tipoDeEnlace] = useState(() => TIPO_DE_TAB_VIEJA[tabUrl] ?? 'todos');
  const tabsVisibles = [
    TAB_TACTICALS,
    ...(puedeVerGrupos ? [TAB_GRUPOS] : []),
    ...(puedeVerProductos ? [TAB_PRODUCTOS] : []),
  ];
  const tab = tabsVisibles.includes(tabUrl) ? tabUrl : TAB_TACTICALS;
  // An old link is rewritten to the tab it opened, so a reload or a shared link does not depend on the old names.
  const esVieja = tabUrl in TIPO_DE_TAB_VIEJA;
  useEffect(() => {
    if (!esVieja) return;
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.delete('seccion');
        params.delete('vista');
        if (tab === TAB_TACTICALS) params.delete('tab');
        else params.set('tab', tab);
        return params;
      },
      { replace: true },
    );
  }, [esVieja, tab, setSearchParams]);

  // The side panel: a tactical line's record, `{ tipo: 'campana' | 'bono' | 'detalle', id }`, read only; null closed.
  const [panel, setPanel] = useState(null);
  const cerrarPanel = useCallback(() => setPanel(null), []);
  const verBono = useCallback((id) => setPanel({ tipo: 'bono', id }), []);
  const verCompra = useCallback((id) => setPanel({ tipo: 'detalle', id }), []);
  // An unknown `origen` opens nothing: its id belongs to no record these panels read.
  const verLinea = useCallback((linea) => {
    const tipo = PANEL_DE_ORIGEN[linea.origen];
    if (tipo) setPanel({ tipo, id: linea.id });
  }, []);

  // Nuevo tactical comes back here with what it created ("Tactical creado: …"), shown once as a toast.
  const navigate = useNavigate();
  const location = useLocation();
  const { toast, showToast, hideToast } = useToast(6000);
  const avisoTactical = location.state?.aviso;
  useEffect(() => {
    if (!avisoTactical) return;
    showToast(avisoTactical);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [avisoTactical, showToast, navigate, location.pathname, location.search]);

  const cambiarTab = (next) => {
    if (next === tab) return;
    setPanel(null);
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === TAB_TACTICALS) params.delete('tab');
        else params.set('tab', next);
        return params;
      },
      { replace: true },
    );
  };
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
  const actualizar = () => setVersionPagina((v) => v + 1);

  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver sell in.
        </div>
      </div>
    );
  }

  const pestana = (id, etiqueta, cuenta) => (
    <button
      key={id}
      type="button"
      role="tab"
      id={`${id}-tab`}
      aria-selected={tab === id}
      aria-controls={tab === id ? `${id}-panel` : undefined}
      tabIndex={tab === id ? 0 : -1}
      className={`${styles.tab} ${tab === id ? styles.tabActive : ''}`}
      onClick={() => cambiarTab(id)}
    >
      <span>{etiqueta}</span>
      {cuenta !== undefined && (
        <>
          {' '}
          <span className={styles.srOnly}>·</span> <span className={styles.tabCount}>{cuenta}</span>
        </>
      )}
    </button>
  );

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Sell in / Sell out</h1>
          <p className={styles.description}>Sell in baja el costo de la compra; sell out suma ganancia por campaña.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className="btn-tesla outline sm" onClick={actualizar}>
            <RefreshCw size={14} /> Actualizar
          </button>
          {tab === TAB_TACTICALS && puedeCrearTactical && (
            <button type="button" className="btn-tesla primary sm" onClick={() => navigate('/sell-in/tactical/nuevo')}>
              <Plus size={14} /> Nuevo tactical
            </button>
          )}
        </div>
      </header>

      <div className={styles.tabs} role="tablist" aria-label="Sell in / Sell out" onKeyDown={onTabsKeyDown}>
        {pestana(
          TAB_TACTICALS,
          'Tacticals',
          tacticals.total != null ? tacticals.total.toLocaleString('es-AR') : tacticals.error ? '—' : '…',
        )}
        {puedeVerGrupos && pestana(TAB_GRUPOS, 'Grupos')}
        {puedeVerProductos && pestana(TAB_PRODUCTOS, 'Productos')}
      </div>

      <SplitPanelLayout
        open={Boolean(panel)}
        onClose={cerrarPanel}
        width="lg"
        ariaLabel={PANEL_LABELS[panel?.tipo] ?? 'Detalle del sell in'}
        panel={
          // From Tacticals a record opens read only: a child is changed only with its tactical (Editar / Anular).
          panel?.tipo === 'bono' ? (
            <SellInBonoPanel
              key={`bono-${panel.id}`}
              bonoId={panel.id}
              marcas={marcas}
              puedeGestionar={false}
              onSaved={actualizar}
              onVerCompra={verCompra}
              onClose={cerrarPanel}
            />
          ) : panel?.tipo === 'producto' ? (
            <SellInProductoCostoPanel
              producto={panel.producto}
              onChanged={() => setVersionProductos((v) => v + 1)}
              onClose={cerrarPanel}
            />
          ) : panel?.tipo === 'campana' ? (
            // A monto total campaign's split (`sell_out.repartir`) still saves from here: the list reads it again.
            <SellOutCampanaPanel
              key={`campana-${panel.id}`}
              campanaId={panel.id}
              puedeGestionar={false}
              onSaved={actualizar}
              onClose={cerrarPanel}
            />
          ) : panel ? (
            <SellInDetailPanel
              key={panel.id}
              compraId={panel.id}
              puedeGestionar={false}
              onChanged={actualizar}
              onVerBono={verBono}
              onClose={cerrarPanel}
            />
          ) : null
        }
      >
        {tab === TAB_PRODUCTOS ? (
          <div role="tabpanel" id="productos-panel" aria-labelledby="productos-tab">
            <SellInProductosCosto
              version={versionPagina + versionProductos}
              onVer={(producto) => setPanel({ tipo: 'producto', producto })}
            />
          </div>
        ) : tab === TAB_GRUPOS ? (
          <div role="tabpanel" id="grupos-panel" aria-labelledby="grupos-tab">
            <GruposTab version={versionPagina} puedeEditar={tienePermiso('config.editar_constantes')} />
          </div>
        ) : (
          <div role="tabpanel" id="tacticals-panel" aria-labelledby="tacticals-tab">
            <TacticalsList
              marcas={marcas}
              version={versionPagina}
              tipoInicial={tipoDeEnlace}
              puedeGestionar={(tipoTactical) => tienePermiso(`${tipoTactical}.gestionar`)}
              onRenovar={(t) => navigate(`/sell-in/tactical/nuevo?tipo=${t.tipo}&renovar=${t.id}`)}
              onCambio={actualizar}
              onVerLinea={verLinea}
            />
          </div>
        )}
      </SplitPanelLayout>
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
