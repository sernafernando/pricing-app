import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Paintbrush } from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useToast } from '../../hooks/useToast';
import Toast from '../Toast';
import { COLORES_DISPONIBLES } from '../../utils/productosConstants';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import styles from './PaintColorMenu.module.css';

const plural = (n, one, many) => (n === 1 ? one : many);

/**
 * Paints the checked products on the layer on show (S8) with Productos' own batch endpoint and rule: the global
 * layer needs `productos.marcar_color_lote`; a team layer, membership (the layer selector lists only the user's
 * teams, the backend checks it again). On success `onPainted` gets the change shaped as the SSE event Productos
 * publishes, so the rows repaint without asking again; on failure nothing changes and the reason is shown.
 */
export default function PaintColorMenu({ checkedIds, equipo, onPainted, onClearChecked }) {
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

  const allowed = equipo ? true : tienePermiso('productos.marcar_color_lote');
  if (checkedIds.size === 0 || !allowed) return <Toast toast={toast} onClose={hideToast} />;

  const n = checkedIds.size;
  const label = `Pintar ${n} ${plural(n, 'producto', 'productos')}`;

  const paint = async (color) => {
    setOpen(false);
    setBusy(true);
    const itemIds = [...checkedIds];
    const equipoId = equipo ? Number(equipo) : null;
    try {
      await api.post('/productos/actualizar-color-lote', {
        item_ids: itemIds,
        color,
        ...(equipoId !== null && { equipo_id: equipoId }),
      });
      onPainted({ data: { vista: 'ml', is_global: equipoId === null, equipo_id: equipoId, item_ids: itemIds, color } });
      onClearChecked?.();
    } catch (error) {
      showToast(apiErrorMessage(error, 'No se pudieron pintar los productos'), 'error');
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
        className="btn-tesla outline-subtle-primary sm"
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
        <div role="menu" aria-label="Colores" className={styles.panel} ref={menuRef} onKeyDown={moveFocus}>
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
