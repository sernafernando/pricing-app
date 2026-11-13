import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Paintbrush } from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useToast } from '../../hooks/useToast';
import Toast from '../Toast';
import { COLORES_DISPONIBLES } from '../../utils/productosConstants';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { paintPublications } from './paintPublications';
import styles from './PaintColorMenu.module.css';
import buttonStyles from './toolbarButton.module.css';

const plural = (n, one, many) => (n === 1 ? one : many);

/**
 * Paints the checked rows on the layer on show (S8): a checked publication paints only itself, never its product
 * (`paintPublications`, seleccion-por-publicacion S3); a checked product row (Producto view) paints its product with
 * Productos' own batch endpoint. Productos' rule: on the global layer one publication needs `productos.marcar_color`,
 * anything more `productos.marcar_color_lote`, plus `productos.marcar_color` when it holds publications; a team layer, membership (the layer selector lists only the user's
 * teams, the backend checks it again). Each part that lands is reported shaped as its SSE event -- `onPaintedOwn`
 * the publications', `onPainted` the products' -- so the rows repaint without asking again. On a failure what did not
 * land stays as it was, the selection too, and the reason is shown.
 */
// `checked`: `{ itemIds, productIds }`, the checked publications and the products of the checked product rows.
// `offPageCount`: how many checked rows the list does not show now (the selection outlives filters and pages).
export default function PaintColorMenu({ checked, offPageCount = 0, equipo, onPainted, onPaintedOwn, onClearChecked }) {
  const { tienePermiso } = usePermisos();
  const { toast, showToast, hideToast } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  // A menu opens on its first item (WAI-ARIA menu button), so the arrows can take it from there.
  useEffect(() => {
    if (open) menuRef.current?.querySelector('[role="menuitem"]')?.focus();
  }, [open]);

  const noteId = useId();
  const { itemIds, productIds } = checked;
  const n = itemIds.length + productIds.length;
  const onlyOne = productIds.length === 0 && itemIds.length === 1;
  // The backend's rule: any write of publications needs `productos.marcar_color`, every batch `marcar_color_lote`.
  const needed = [...(itemIds.length > 0 ? ['productos.marcar_color'] : []), ...(onlyOne ? [] : ['productos.marcar_color_lote'])];
  const allowed = equipo ? true : needed.every((permiso) => tienePermiso(permiso));
  if (n === 0 || !allowed) return <Toast toast={toast} onClose={hideToast} />;

  const label =
    productIds.length === 0
      ? `Pintar ${n} ${plural(n, 'publicación', 'publicaciones')}`
      : itemIds.length === 0
        ? `Pintar ${n} ${plural(n, 'producto', 'productos')}`
        : `Pintar ${n} filas`;

  const paint = async (color) => {
    setOpen(false);
    setBusy(true);
    const equipoId = equipo ? Number(equipo) : null;
    try {
      try {
        await paintPublications(itemIds, color, equipoId, onPaintedOwn);
      } catch (error) {
        throw new Error(apiErrorMessage(error, 'No se pudieron pintar las publicaciones'));
      }
      if (productIds.length > 0) {
        try {
          await api.post('/productos/actualizar-color-lote', {
            item_ids: productIds,
            color,
            ...(equipoId !== null && { equipo_id: equipoId }),
          });
        } catch (error) {
          throw new Error(apiErrorMessage(error, 'No se pudieron pintar los productos'));
        }
        onPainted({ data: { vista: 'ml', is_global: equipoId === null, equipo_id: equipoId, item_ids: productIds, color } });
      }
      onClearChecked?.();
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    }
  };

  const moveFocus = (event) => {
    const items = [...menuRef.current.querySelectorAll('[role="menuitem"]')];
    const at = items.indexOf(document.activeElement);
    const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    items[(next + items.length) % items.length].focus();
  };

  return (
    <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
      <button
        ref={triggerRef}
        type="button"
        className={`btn-tesla sm ${buttonStyles.quiet}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={`${label} en la capa ${equipo ? 'del equipo' : 'global'}`}
        disabled={busy}
        onClick={() => setOpen((was) => !was)}
      >
        <Paintbrush size={14} aria-hidden="true" />
        Pintar
        <span className={styles.count}>{n}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Colores"
          aria-describedby={offPageCount > 0 ? noteId : undefined}
          className={styles.panel}
          ref={menuRef}
          onKeyDown={moveFocus}
        >
          {offPageCount > 0 && (
            // Read as the menu's description: a menu holds only its items.
            <p id={noteId} role="none" className={styles.note}>
              {offPageCount} {plural(offPageCount, 'fila marcada no está', 'filas marcadas no están')} en esta página
            </p>
          )}
          {COLORES_DISPONIBLES.map((c) => (
            <button key={c.id ?? 'none'} type="button" role="menuitem" className={styles.item} onClick={() => paint(c.id)}>
              <span className={styles.swatch} data-empty={c.color ? undefined : ''} style={c.color ? { background: c.color } : undefined} />
              {c.nombre}
            </button>
          ))}
        </div>
      )}
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
