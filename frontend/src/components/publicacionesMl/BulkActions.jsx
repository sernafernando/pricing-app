import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Layers, X } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import { useToast } from '../../hooks/useToast';
import Toast from '../Toast';
import AplicarMarkupMasivoModal from '../AplicarMarkupMasivoModal';
import CalcularWebModal from '../CalcularWebModal';
import CalcularPVPModal from '../CalcularPVPModal';
import { buildItemsParams, buildProductIdsParams } from '../../hooks/usePublicacionesMLFilters';
import useBulkProductSet from './useBulkProductSet';
import styles from './BulkActions.module.css';

// Productos' bulk actions, behind Productos' own permissions.
const ACTIONS = [
  { key: 'web', label: 'Calcular Web Transf.', permiso: 'productos.calcular_web_masivo' },
  { key: 'pvp', label: 'Calcular PVP', permiso: 'productos.calcular_pvp_masivo' },
  { key: 'markup', label: 'Markup y cuotas', permiso: 'productos.aplicar_markup_masivo' },
];

const plural = (n, one, many) => (n === 1 ? one : many);
const MARKUP_KEYS = ['markup_neg', 'markup_min', 'markup_max'];

/**
 * What the resolver is asked: the list's filters and, where the list applies them (the publication list, with
 * `ml_metricas.ver_ganancia`), its markup filters exactly as `/items` gets them -- the resolver applies them the
 * same way, so the set is the products of the publications the operator sees.
 */
function resolverParams(filters, canSeeMargin) {
  const params = buildProductIdsParams(filters);
  if (!canSeeMargin || filters.vista === 'producto' || filters.vista === 'agrupado') return params;
  const listed = buildItemsParams(filters, 1, { canSeeMargin: true });
  for (const key of MARKUP_KEYS) if (key in listed) params[key] = listed[key];
  return params;
}

/**
 * Productos' bulk pricing actions (web transferencia, PVP, markup + cuotas) over Publicaciones ML. Pricing is per
 * product, so they act on PRODUCTS: the ones the operator checked in the list, else the linked products of every
 * publication the filters select (`useBulkProductSet`), sent to Productos' own modals as an explicit `itemIds` set.
 *
 * Fail closed, with the reason on the button: no set while it is resolving, when the resolver refuses (over its
 * cap) or fails, or when it is empty. Publications without a product and linked products gone from the ERP catalog
 * are left out by the resolver, and the menu says how many.
 */
export default function BulkActions({ filters, checkedIds, onClearChecked, canSeeMargin, onDone }) {
  const { tienePermiso } = usePermisos();
  const { toast, showToast, hideToast } = useToast();
  const actions = ACTIONS.filter((action) => tienePermiso(action.permiso));
  const [open, setOpen] = useState(false);
  const [modal, setModal] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const containerRef = useRef(null);

  const resolved = useBulkProductSet(resolverParams(filters, canSeeMargin), actions.length > 0, reloadToken);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  if (actions.length === 0) return null;

  const checked = checkedIds.size > 0;
  const itemIds = checked ? [...checkedIds] : resolved.itemIds;
  let reason = null;
  if (!checked) {
    if (resolved.status === 'error') reason = resolved.error;
    else if (resolved.status !== 'ready') reason = 'Calculando los productos del filtro…';
    else if (itemIds.length === 0) reason = 'El filtro no selecciona ningún producto vinculado.';
  }
  const n = itemIds.length;
  const scope = checked
    ? `${n} ${plural(n, 'producto seleccionado', 'productos seleccionados')}`
    : reason
      ? null
      : `${n} ${plural(n, 'producto', 'productos')}`;
  const notas = checked
    ? []
    : [
        resolved.sinProducto > 0 &&
          `${resolved.sinProducto} ${plural(resolved.sinProducto, 'publicación sin producto queda afuera', 'publicaciones sin producto quedan afuera')}`,
        resolved.fueraDeCatalogo > 0 &&
          `${resolved.fueraDeCatalogo} ${plural(resolved.fueraDeCatalogo, 'producto fuera del catálogo queda afuera', 'productos fuera del catálogo quedan afuera')}`,
      ].filter(Boolean);
  const nota = notas.length > 0 ? notas.join('. ') : null;

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const openModal = (key) => {
    setOpen(false);
    setModal(key);
  };
  const done = () => {
    setReloadToken((token) => token + 1);
    onDone?.();
  };
  const modalProps = { onClose: () => setModal(null), onSuccess: done, showToast, itemIds, itemIdsNota: nota };

  return (
    <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
      <button
        type="button"
        className="btn-tesla outline-subtle-primary sm"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={scope ? `Acciones masivas (${scope})` : 'Acciones masivas'}
        title={reason ?? `Cambia el precio de ${scope}, en todas sus publicaciones`}
        disabled={Boolean(reason)}
        onClick={() => setOpen((was) => !was)}
      >
        <Layers size={14} aria-hidden="true" />
        Acciones masivas
        {scope && <span className={styles.count}>{n}</span>}
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.panel}>
          <p className={styles.scope}>
            Sobre {checked ? scope : `los ${scope} del filtro`}
          </p>
          {nota && <p className={styles.note}>{nota}</p>}
          <div role="menu" aria-label="Acciones masivas" className={styles.menu}>
            {actions.map((action) => (
              <button key={action.key} type="button" role="menuitem" className={styles.item} onClick={() => openModal(action.key)}>
                {action.label}
              </button>
            ))}
          </div>
          {checked && (
            <button type="button" className="btn-tesla ghost sm" onClick={onClearChecked}>
              <X size={14} aria-hidden="true" />
              Limpiar selección
            </button>
          )}
        </div>
      )}
      {modal === 'web' && <CalcularWebModal {...modalProps} />}
      {modal === 'pvp' && <CalcularPVPModal {...modalProps} />}
      {modal === 'markup' && (
        <AplicarMarkupMasivoModal {...modalProps} puedeEditarCuotas={tienePermiso('productos.editar_precio_cuotas')} />
      )}
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
