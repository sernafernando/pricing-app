import { useEffect, useLayoutEffect, useRef } from 'react';

const ROW = 'tr[data-clickable][data-row-key]';
const PAGE = 10;
const TYPING = 'input, textarea, select, [contenteditable="true"]';

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
 * - Ctrl+F focuses the search, Ctrl+E exports (only where the view can: `onExport` absent leaves it to the browser),
 *   `?` toggles the help.
 * - Ctrl+F1/F2/F3 (or Ctrl+Shift+1/2/3) copy the focused publication's product code and its two ML links.
 *
 * Nothing here runs while the operator types in a field, except Ctrl+F. `findRow(key)` maps a focused row's key to
 * its row (a publication with `link.codigo`), so copying works wherever the rows are publications.
 */
export default function usePublicacionesMLKeyboard({ searchRef, findRow, onExport, onToggleHelp, showToast, disabled }) {
  // The latest props, so the one listener never reads stale ones (updated after each render, never during it).
  const props = useRef({});
  useLayoutEffect(() => {
    props.current = { searchRef, findRow, onExport, onToggleHelp, showToast };
  });

  useEffect(() => {
    if (disabled) return undefined;
    const copy = (action) => {
      const { findRow: find, showToast: toast } = props.current;
      const key = focusedRow()?.dataset.rowKey;
      const row = key === undefined ? null : find?.(key);
      if (!row) {
        toast?.('Posicionate sobre una publicación (flecha abajo) para usar este atajo', 'error');
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
      const { searchRef: search, onExport: exportView, onToggleHelp: toggleHelp } = props.current;
      const action = copyAction(event);
      if (action) {
        event.preventDefault();
        copy(action);
        return;
      }
      if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key === 'f' && search?.current) {
        event.preventDefault();
        search.current.focus();
        return;
      }
      if (isTyping(event.target)) return;
      if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key === 'e' && exportView) {
        event.preventDefault();
        exportView();
        return;
      }
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      if (event.key === '?' && toggleHelp) {
        event.preventDefault();
        toggleHelp();
        return;
      }
      if (moveFocus(event)) event.preventDefault();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [disabled]);
}
