import { useLayoutEffect, useState } from 'react';

/**
 * What one cell's content takes, in px: from the leftmost to the rightmost piece it holds -- its text, and every box
 * whose width is its own (badges, sparklines, icons, a nowrap line wider than the cell) -- plus the cell's horizontal
 * padding. A box exactly as wide as the cell's content area is taken as stretched to it and left out (its text still
 * counts), so the figure never depends on the column's current width, which would feed back into itself. Pieces out
 * of the flow are skipped. Text that overflows the cell on either side still counts. 0 without layout (jsdom).
 */
function contentWidth(cell) {
  const doc = cell.ownerDocument;
  const range = doc.createRange();
  if (typeof range.getBoundingClientRect !== 'function') return 0;
  const style = getComputedStyle(cell);
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const stretched = cell.clientWidth - padding;
  let left = Infinity;
  let right = -Infinity;
  const take = (rect) => {
    if (!rect || rect.width === 0) return;
    left = Math.min(left, rect.left);
    right = Math.max(right, rect.right);
  };
  // Out-of-flow pieces (a screen-reader-only note, a popover) take no room in the column: skipped with what they hold.
  const walker = doc.createTreeWalker(cell, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) =>
      node.nodeType === Node.ELEMENT_NODE && /^(absolute|fixed)$/.test(getComputedStyle(node).position)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!node.textContent.trim()) continue;
      range.selectNodeContents(node);
      take(range.getBoundingClientRect());
    } else {
      const rect = node.getBoundingClientRect();
      if (Math.abs(rect.width - stretched) > 0.5) take(rect);
    }
  }
  if (right < left) return 0;
  return right - left + padding;
}

/** `previous` with every width `measured` grows; the same object when nothing grew (no re-render). */
function grown(previous, measured) {
  let next = previous;
  for (const [key, width] of Object.entries(measured)) {
    if (width > (previous[key] ?? 0) + 1) {
      if (next === previous) next = { ...previous };
      next[key] = width;
    }
  }
  return next;
}

/**
 * The widths (px) the `fit` columns of a table need, measured in the browser from the header and the cells in the
 * DOM (`[data-column=<key>]`), so a column holds its widest value in whatever font the browser has. Widths only grow
 * while the same columns show (rows scrolling in, a new page), so the table never jumps narrower under the pointer;
 * a different set of `fit` columns starts over. `deps` re-measures (the rows, the virtual window).
 */
export function useFitColumnWidths(tableRef, columns, deps) {
  const keys = columns
    .filter((column) => column.fit)
    .map((column) => column.key)
    .join(',');
  const [state, setState] = useState({ keys, widths: {} });
  const widths = state.keys === keys ? state.widths : {};

  useLayoutEffect(() => {
    const table = tableRef.current;
    // No layout (jsdom, a hidden table): nothing to measure, and walking every cell would only cost time.
    if (!table || !keys || !table.getBoundingClientRect().width) return undefined;
    const measure = () => {
      const measured = {};
      for (const key of keys.split(',')) {
        let need = 0;
        for (const cell of table.querySelectorAll(`[data-column="${CSS.escape(key)}"]`)) {
          need = Math.max(need, contentWidth(cell));
        }
        if (need > 0) measured[key] = Math.ceil(need);
      }
      setState((previous) => {
        const base = previous.keys === keys ? previous : { keys, widths: {} };
        const next = grown(base.widths, measured);
        return next === base.widths && base === previous ? previous : { keys, widths: next };
      });
    };
    measure();
    // A web font that arrives late changes every figure's width.
    let live = true;
    document.fonts?.ready?.then(() => live && measure());
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableRef, keys, ...deps]);

  return widths;
}
