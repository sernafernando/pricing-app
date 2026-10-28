import { useEffect, useLayoutEffect, useRef, useState } from 'react';

const ROW = 'tr[data-clickable][data-row-key]';
const PAGE = 10;
const TYPING = 'input, textarea, select, [contenteditable="true"]';
// The shortcuts' own help is a dialog too, but `?` must still close it.
export const HELP_CLASS = 'publicaciones-ml-shortcuts-help';

// Productos' clipboard shortcuts (`useProductosKeyboard`): the product code and its two Mercado Libre links.
const COPIES = {
  1: { text: (codigo) => codigo, label: 'Código copiado' },
  2: { text: (codigo) => `https://listado.mercadolibre.com.ar/${codigo}_OrderId_PRICE_NoIndex_True`, label: 'Enlace 1 copiado' },
  3: {
    text: (codigo) =>
      `https://www.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=${codigo}&sort=lowest_price`,
    label: 'Enlace 2 copiado',
  },
};

// Productos' quick colors (`useProductosKeyboard`): the digit is the index, 0 clears the color.
const PAINT_COLORS = [null, 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
// Alt+letter opens a filter, by the key (`code`): a Mac types another character with Alt. Productos' Alt+C and Alt+F
// both open its Avanzados (rebate, oferta, web transf., fuera de tarjetas): here those are the presence filters.
// Each value is the `data-filter` of a filter button the page clicks (ProductFiltersPanel, AuditFilters,
// PresenceFilters): renaming one side breaks the key.
const FILTER_KEYS = {
  KeyM: 'marcas',
  KeyS: 'subcategorias',
  KeyP: 'pms',
  KeyA: 'auditoria',
  KeyC: 'presencia',
  KeyF: 'presencia',
};
const NO_ROW = 'Posicionate sobre una publicación (flecha abajo) para usar este atajo';

function copyAction(event) {
  if (!event.ctrlKey) return null;
  if (!event.shiftKey && /^F[123]$/.test(event.key)) return Number(event.key[1]);
  if (event.shiftKey) {
    if (event.code === 'Digit1' || event.key === '!') return 1;
    if (event.code === 'Digit2' || event.key === '@' || event.key === '"') return 2;
    if (event.code === 'Digit3' || event.key === '#' || event.key === '·') return 3;
  }
  return null;
}

// r / w / o, as in Productos.
const TOGGLE_KEYS = { KeyR: 'rebate', KeyW: 'web', KeyO: 'tarjetas' };

const isTyping = (element) => Boolean(element?.closest?.(TYPING));
const focusedRow = () => document.activeElement?.closest?.(ROW) ?? null;

/** The rows of the table the focused row is in (or the page's first table), in screen order. */
function rowsAround(current) {
  const scope = current?.closest('tbody') ?? document.querySelector(`tbody:has(${ROW})`) ?? document;
  return Array.from(scope.querySelectorAll(ROW));
}

function moveFocus(event) {
  const current = focusedRow();
  const rows = rowsAround(current);
  if (rows.length === 0) return false;
  const index = current ? rows.indexOf(current) : -1;
  let next;
  if (index === -1) {
    // Only from nowhere: an arrow inside the panel or a menu belongs to it.
    const nowhere = !document.activeElement || document.activeElement === document.body;
    if (event.key !== 'ArrowDown' || !nowhere) return false;
    next = 0;
  } else if (event.key === 'ArrowDown') next = index + 1;
  else if (event.key === 'ArrowUp') next = index - 1;
  else if (event.key === 'PageDown') next = index + PAGE;
  else if (event.key === 'PageUp') next = index - PAGE;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = rows.length - 1;
  else return false;
  const target = rows[Math.max(0, Math.min(rows.length - 1, next))];
  target.focus();
  target.scrollIntoView?.({ block: 'nearest' });
  return true;
}

/**
 * Publicaciones ML's keyboard shortcuts: Productos' (`useProductosKeyboard`) over what this screen has.
 *
 * - The arrows, PageUp/PageDown (ten rows) and Home/End move the focus over the list's rows; ArrowDown with no row
 *   focused (and nothing else focused) enters on the first one. Enter opens the focused row (the table's own key; Ctrl+Enter opens it in ML).
 * - Ctrl+I (Cmd+I) opens Productos' information of the focused row's product (`onShowInfo(key)`), as in Productos.
 * - Ctrl+F focuses the search, Ctrl+E exports (only where the view can: `onExport` absent leaves it to the browser),
 *   `?` toggles the help.
 * - Ctrl+F1/F2/F3 (or Ctrl+Shift+1/2/3) copy the focused publication's product code and its two ML links.
 * - 0-7 paint the focused row's product (`onPaintRow(key, color)`, 0 = no color) and F6/F7 step to the previous /
 *   next color layer (`onCycleLayer(-1 | 1)`), as in Productos; each only where the page offers it.
 * - Ctrl+K / Ctrl+Shift+P open the bulk Calcular Web Transf. / Calcular PVP (`onBulkAction('web' | 'pvp')`), and
 *   Alt+M / Alt+S / Alt+P the Marca / Subcategoría / PM filters, Alt+A the Auditoría ones and Alt+C / Alt+F the
 *   presence ones (Productos' Avanzados) (`onOpenFilter(name)`), as in Productos.
 * - r / w / o flip the focused row's product rebate, web transfer and "fuera de tarjetas" (`onToggleRow(key, 'rebate' |
 *   'web' | 'tarjetas')`), as in Productos.
 * - Alt+V steps to the next mode of Productos' price columns (`onCycleMode()`: Normal, Cuotas, PVP), and Alt+R flips
 *   Productos' "Auto-recalcular" cuotas (`onToggleAutoRecalc()`), as in Productos.
 * - Shift+Up / Shift+Down move like the arrows and check the row moved to (`onExtendRow(key)`), as in Productos.
 * - A focused row is Productos' navigation mode (the returned `navigating`, for its banner) and Escape leaves it,
 *   taking the focus off the row; while the side panel is open Escape is the panel's (`keepRowOnEscape`).
 *
 * While the operator types in a field only Ctrl+F and the copy shortcuts run (as in Productos, which copies while
 * editing too); nothing runs while a dialog is open (the help only takes `?`, to close it). `findRow(key)` maps a focused row's key to
 * its row (a publication with `link.codigo`), so copying works wherever the rows are publications.
 */
export default function usePublicacionesMLKeyboard({
  searchRef,
  findRow,
  onExport,
  onPaintRow,
  onToggleRow,
  onExtendRow,
  onCycleLayer,
  onCycleMode,
  onBulkAction,
  onOpenFilter,
  onToggleAutoRecalc,
  onShowInfo,
  onToggleHelp,
  keepRowOnEscape,
  showToast,
  disabled,
}) {
  const [navigating, setNavigating] = useState(false);
  // The latest props, so the one listener never reads stale ones (updated after each render, never during it).
  // No dependency array on purpose (the latest-ref pattern): it copies the values after every render.
  const props = useRef({});
  useLayoutEffect(() => {
    props.current = { searchRef, findRow, onExport, onPaintRow, onToggleRow, onExtendRow, onCycleLayer, onCycleMode, onBulkAction, onOpenFilter, onToggleAutoRecalc, onShowInfo, onToggleHelp, keepRowOnEscape, showToast };
  });

  useEffect(() => {
    if (disabled) return undefined;
    const copy = (action) => {
      const { findRow: find, showToast: toast } = props.current;
      const key = focusedRow()?.dataset.rowKey;
      if (key === undefined) {
        toast?.(NO_ROW, 'error');
        return;
      }
      const row = find?.(key);
      if (!row) {
        toast?.('Los atajos de copia funcionan en la vista Publicaciones', 'error');
        return;
      }
      const codigo = row.link?.codigo;
      if (!codigo) {
        toast?.('La publicación no tiene producto vinculado', 'error');
        return;
      }
      const { text, label } = COPIES[action];
      navigator.clipboard
        .writeText(text(codigo))
        .then(() => toast?.(`${label}: ${codigo}`))
        .catch(() => toast?.('No se pudo copiar al portapapeles', 'error'));
    };

    const handleKeyDown = (event) => {
      const {
        searchRef: search,
        onExport: exportView,
        onToggleHelp: toggleHelp,
        onPaintRow: paintRow,
        onToggleRow: toggleRow,
        onExtendRow: extendRow,
        onCycleLayer: cycleLayer,
        onCycleMode: cycleMode,
        onBulkAction: bulkAction,
        onOpenFilter: openFilter,
        onToggleAutoRecalc: toggleAutoRecalc,
        onShowInfo: showInfo,
        keepRowOnEscape: keepRow,
        showToast: toast,
      } = props.current;
      // Another dialog (a bulk action, a confirmation, Productos' info modal) owns the keyboard, as in Productos; the
      // help only lets `?` close it. The info modal is matched by its own class: `.modal-overlay` alone is shared by
      // unrelated components.
      const dialog = document.querySelector('.modal-overlay-tesla, .modal-info-producto');
      if (dialog) {
        if (event.key === '?' && toggleHelp && dialog.querySelector(`.${HELP_CLASS}`) && !isTyping(event.target)) {
          event.preventDefault();
          toggleHelp();
        }
        return;
      }
      const action = copyAction(event);
      if (action) {
        event.preventDefault();
        copy(action);
        return;
      }
      // `code`, not `key`: Caps Lock turns the key into 'F' / 'E'.
      if (event.ctrlKey && !event.shiftKey && !event.altKey && event.code === 'KeyF' && search?.current) {
        event.preventDefault();
        search.current.focus();
        return;
      }
      if (isTyping(event.target)) return;
      // Escape is taken only when it leaves a row: with no row focused, or with a modifier, it stays for the others.
      const current = focusedRow();
      const plain = !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey;
      if (event.key === 'Escape' && plain && current && !keepRow && !event.defaultPrevented) {
        event.preventDefault();
        current.blur();
        return;
      }
      // Cmd+I too, as Productos accepts it (`e.ctrlKey || e.metaKey`), unlike the Alt keys below.
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.code === 'KeyI' && showInfo) {
        event.preventDefault();
        const key = focusedRow()?.dataset.rowKey;
        if (key === undefined) toast?.(NO_ROW, 'error');
        else showInfo(key);
        return;
      }
      if (event.ctrlKey && !event.shiftKey && !event.altKey && event.code === 'KeyE' && exportView) {
        event.preventDefault();
        exportView();
        return;
      }
      if (event.ctrlKey && !event.altKey && bulkAction) {
        const bulk = event.code === 'KeyK' && !event.shiftKey ? 'web' : event.code === 'KeyP' && event.shiftKey ? 'pvp' : null;
        if (bulk) {
          event.preventDefault();
          bulkAction(bulk);
          return;
        }
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey && FILTER_KEYS[event.code] && openFilter) {
        event.preventDefault();
        openFilter(FILTER_KEYS[event.code]);
        return;
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyR' && toggleAutoRecalc) {
        event.preventDefault();
        // A held key repeats: each repeat would flip it again.
        if (!event.repeat) toggleAutoRecalc();
        return;
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyV' && cycleMode) {
        event.preventDefault();
        cycleMode();
        return;
      }
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      if ((event.key === 'F6' || event.key === 'F7') && !event.shiftKey && cycleLayer) {
        event.preventDefault();
        cycleLayer(event.key === 'F7' ? 1 : -1);
        return;
      }
      if (/^[0-7]$/.test(event.key) && paintRow) {
        event.preventDefault();
        const key = focusedRow()?.dataset.rowKey;
        if (key === undefined) toast?.(NO_ROW, 'error');
        else paintRow(key, PAINT_COLORS[Number(event.key)]);
        return;
      }
      // `code`: Caps Lock or a layout must not change which toggle a key flips; Shift+R and the like are not it.
      if (TOGGLE_KEYS[event.code] && !event.shiftKey && toggleRow) {
        event.preventDefault();
        // A held key repeats: each repeat would flip it again.
        if (event.repeat) return;
        const key = focusedRow()?.dataset.rowKey;
        if (key === undefined) toast?.(NO_ROW, 'error');
        else toggleRow(key, TOGGLE_KEYS[event.code]);
        return;
      }
      if (event.key === '?' && toggleHelp) {
        event.preventDefault();
        toggleHelp();
        return;
      }
      const before = focusedRow();
      if (moveFocus(event)) {
        event.preventDefault();
        // Shift+Up / Shift+Down check the row moved to (S12d, Productos); a move that stays put checks nothing.
        const after = focusedRow();
        if (event.shiftKey && extendRow && (event.key === 'ArrowUp' || event.key === 'ArrowDown') && after && after !== before) {
          extendRow(after.dataset.rowKey);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [disabled]);

  // Navigating = a list row has the focus. On `focusout` the next element is `relatedTarget` (null when the focus
  // leaves to nowhere), since `document.activeElement` is still the row being left.
  useEffect(() => {
    const onFocusIn = (event) => setNavigating(Boolean(event.target?.closest?.(ROW)));
    const onFocusOut = (event) => setNavigating(Boolean(event.relatedTarget?.closest?.(ROW)));
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    return () => {
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', onFocusOut);
    };
  }, []);

  // A focused row taken out of the list (another page, a refetch) may leave without a `focusout`: while navigating,
  // each change to the page checks the row is still there.
  useEffect(() => {
    if (!navigating) return undefined;
    const observer = new MutationObserver(() => {
      if (!focusedRow()) setNavigating(false);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [navigating]);

  return { navigating: navigating && !disabled };
}
