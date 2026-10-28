import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, Layers, X } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import { useToast } from '../../hooks/useToast';
import Toast from '../Toast';
import AplicarMarkupMasivoModal from '../AplicarMarkupMasivoModal';
import CalcularWebModal from '../CalcularWebModal';
import CalcularPVPModal from '../CalcularPVPModal';
import RecalcularCuotasModal from './RecalcularCuotasModal';
import useBulkProductSet from './useBulkProductSet';
import { resolverParams } from './bulkParams';
import styles from './BulkActions.module.css';

// Productos' bulk actions, behind Productos' own permissions. The cuotas recalculation is Productos' "Recalcular
// Cuotas Web/PVP" button, which Productos shows in its Cuotas/PVP view modes.
const ACTIONS = [
  { key: 'web', label: 'Calcular Web Transf.', permiso: 'productos.calcular_web_masivo' },
  { key: 'pvp', label: 'Calcular PVP', permiso: 'productos.calcular_pvp_masivo' },
  { key: 'markup', label: 'Markup y cuotas', permiso: 'productos.aplicar_markup_masivo' },
  { key: 'cuotas-web', label: 'Recalcular cuotas Web', permiso: 'productos.editar_precio_cuotas' },
  { key: 'cuotas-pvp', label: 'Recalcular cuotas PVP', permiso: 'productos.editar_precio_cuotas' },
];

const plural = (n, one, many) => (n === 1 ? one : many);

/**
 * Productos' bulk pricing actions (web transferencia, PVP, markup + cuotas, cuotas recalculation) over Publicaciones ML. Pricing is per
 * product, so they act on PRODUCTS: the ones the operator checked in the list, else the linked products of every
 * publication the filters select (`useBulkProductSet`), sent to Productos' own modals as an explicit `itemIds` set.
 *
 * Fail closed, with the reason on the button: no set while it is resolving, when the resolver refuses (over its
 * cap) or fails, or when it is empty. Publications without a product and linked products gone from the ERP catalog
 * are left out by the resolver, and the menu says how many.
 */
// `openRequest` ({ key, at }: a new `at` per request) opens an action's modal as its menu item would -- Ctrl+K and
// Ctrl+Shift+P, as in Productos. An action the user may not run opens nothing; a set not ready yet says why.
// `offPageCount`: how many checked products the list does not show now (the selection outlives filters and pages).
export default function BulkActions({ filters, checkedIds, offPageCount = 0, onClearChecked, canSeeMargin, onDone, openRequest }) {
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
    ? [
        offPageCount > 0 &&
          `${offPageCount} ${plural(offPageCount, 'producto seleccionado no está', 'productos seleccionados no están')} en esta página (se eligieron con otros filtros o en otra página)`,
      ].filter(Boolean)
    : [
        resolved.sinProducto > 0 &&
          `${resolved.sinProducto} ${plural(resolved.sinProducto, 'publicación sin producto queda afuera', 'publicaciones sin producto quedan afuera')}`,
        resolved.fueraDeCatalogo > 0 &&
          `${resolved.fueraDeCatalogo} ${plural(resolved.fueraDeCatalogo, 'producto fuera del catálogo queda afuera', 'productos fuera del catálogo quedan afuera')}`,
      ].filter(Boolean);
  const nota = notas.length > 0 ? notas.join('. ') : null;

  // The request is answered with this render's set (updated before effects run), once per `at`.
  // No dependency array on purpose (the latest-ref pattern): it copies the values after every render.
  const current = useRef({});
  useLayoutEffect(() => {
    current.current = { actions, reason, itemIds, nota };
  });
  const handledRequest = useRef(null);
  useEffect(() => {
    if (!openRequest || handledRequest.current === openRequest.at) return;
    handledRequest.current = openRequest.at;
    const { actions: allowed, reason: blocked, itemIds: ids, nota: note } = current.current;
    if (!allowed.some((action) => action.key === openRequest.key)) return;
    if (blocked) {
      showToast(blocked, 'error');
      return;
    }
    setOpen(false);
    setModal({ key: openRequest.key, itemIds: ids, itemIdsNota: note });
  }, [openRequest, showToast]);

  if (actions.length === 0) return null;

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  // The open modal keeps the set (and its note) the operator reviewed when opening it: a run re-resolves the set
  // for the next open, and a second run from the same modal acts on the same products.
  const openModal = (key) => {
    setOpen(false);
    setModal({ key, itemIds, itemIdsNota: nota });
  };
  const done = () => {
    setReloadToken((token) => token + 1);
    onDone?.();
  };
  const modalProps = modal && {
    onClose: () => setModal(null),
    onSuccess: done,
    showToast,
    itemIds: modal.itemIds,
    itemIdsNota: modal.itemIdsNota,
  };

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
      {modal?.key === 'web' && <CalcularWebModal {...modalProps} />}
      {modal?.key === 'pvp' && <CalcularPVPModal {...modalProps} />}
      {modal?.key === 'markup' && (
        <AplicarMarkupMasivoModal {...modalProps} puedeEditarCuotas={tienePermiso('productos.editar_precio_cuotas')} />
      )}
      {modal?.key === 'cuotas-web' && <RecalcularCuotasModal {...modalProps} listaTipo="web" />}
      {modal?.key === 'cuotas-pvp' && <RecalcularCuotasModal {...modalProps} listaTipo="pvp" />}
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
