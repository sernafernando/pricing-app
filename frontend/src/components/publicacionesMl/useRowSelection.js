import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/** The selection key of a publication row, and of a product row (Producto view). */
export const publicationKey = (itemId) => `i:${itemId}`;
export const productKey = (productId) => (productId == null ? null : `p:${productId}`);

const indexOf = (rows, key) => rows.findIndex((row) => row.key === key);
const rowOf = (rows, key) => rows.find((row) => row.key === key) ?? { key, productId: null, itemId: null };
const range = (rows, from, to) => rows.slice(Math.min(from, to), Math.max(from, to) + 1);

/**
 * The rows checked in Publicaciones ML, as Productos' selection (`useProductosSeleccion`) but per ROW: a publication
 * checks itself, not its product, and a product row (Producto view) checks its product. `order` is the rows on show,
 * `{ key, productId, itemId }` each (repeats allowed; a null key cannot be checked): a toggle checks or unchecks one
 * row; with Shift it checks every row between the last one toggled and this one. `extendTo` (Shift+arrows) checks
 * that range too, or just the row when the range has no start on show, and never unchecks. The selection outlives
 * the rows: another filter, page or view keeps it, with each row's product and publication as they were when checked.
 *
 * `productIds` is the distinct products behind the checked rows (a product row's own, a publication's linked one),
 * for the per-product actions; `itemIds`, the checked publications. `togglePage` checks every row on show, or unchecks
 * them when they all are, leaving the rest as it was. `pageState` says how many of the page's rows are checked:
 * 'empty' (none to check), 'none', 'some' or 'all'; `offPageCount`, how many checked rows are not on show.
 */
export default function useRowSelection(order) {
  const [checked, setChecked] = useState(() => new Map());
  // Where a Shift range starts: the row toggled last.
  const anchor = useRef(null);
  const page = useMemo(() => {
    const byKey = new Map();
    order.forEach((row) => {
      if (row.key != null && !byKey.has(row.key)) byKey.set(row.key, row);
    });
    return [...byKey.values()];
  }, [order]);
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  const onToggle = useCallback((key, extend = false) => {
    const rows = pageRef.current;
    const from = indexOf(rows, anchor.current);
    const to = indexOf(rows, key);
    setChecked((current) => {
      const next = new Map(current);
      if (extend && from !== -1 && to !== -1) range(rows, from, to).forEach((row) => next.set(row.key, row));
      else if (!next.delete(key)) next.set(key, rowOf(rows, key));
      return next;
    });
    anchor.current = key;
  }, []);

  // Shift+Up / Shift+Down: the range from the row toggled last, or only this row when that one is not on show. It
  // only checks: moving over a checked row never unchecks it.
  const extendTo = useCallback((key) => {
    const rows = pageRef.current;
    const from = indexOf(rows, anchor.current);
    const to = indexOf(rows, key);
    setChecked((current) => {
      const next = new Map(current);
      if (from !== -1 && to !== -1) range(rows, from, to).forEach((row) => next.set(row.key, row));
      else next.set(key, rowOf(rows, key));
      return next;
    });
    anchor.current = key;
  }, []);

  const pageState = useMemo(() => {
    if (page.length === 0) return 'empty';
    const on = page.filter((row) => checked.has(row.key)).length;
    return on === 0 ? 'none' : on === page.length ? 'all' : 'some';
  }, [page, checked]);

  const offPageCount = useMemo(() => {
    const shown = new Set(page.map((row) => row.key));
    return [...checked.keys()].filter((key) => !shown.has(key)).length;
  }, [page, checked]);

  const productIds = useMemo(
    () => new Set([...checked.values()].map((row) => row.productId).filter((id) => id !== null && id !== undefined)),
    [checked],
  );
  const itemIds = useMemo(() => [...checked.values()].map((row) => row.itemId).filter(Boolean), [checked]);

  const togglePage = useCallback(() => {
    const rows = pageRef.current;
    if (rows.length === 0) return;
    setChecked((current) => {
      const next = new Map(current);
      if (rows.every((row) => current.has(row.key))) rows.forEach((row) => next.delete(row.key));
      else rows.forEach((row) => next.set(row.key, row));
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setChecked(new Map());
    anchor.current = null;
  }, []);

  return { checked, productIds, itemIds, onToggle, extendTo, togglePage, clear, pageState, offPageCount };
}
