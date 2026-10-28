import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const known = (id) => id !== null && id !== undefined;

/**
 * The products checked for the bulk pricing actions (S12d), with Productos' selection (`useProductosSeleccion`):
 * a toggle checks or unchecks one product; with Shift it checks every product between the last one toggled and
 * this one, in the order they are on show (`order`: the rows' product ids, repeats and nulls allowed). `extendTo`
 * (Shift+arrows) checks that range too, or just the product when the range has no start on show, and never unchecks.
 * The selection outlives the rows: another filter, page or view keeps it.
 *
 * `togglePage` checks every product on show, or unchecks them when they all are, leaving the products checked
 * elsewhere as they were. `pageState` says how many of the page's products are checked: 'empty' (none to check),
 * 'none', 'some' or 'all'; `offPageCount`, how many checked products are not on show.
 */
export default function useProductSelection(order) {
  const [checked, setChecked] = useState(() => new Set());
  // Where a Shift range starts: the product toggled last.
  const anchor = useRef(null);
  const page = useMemo(() => [...new Set(order.filter(known))], [order]);
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  const onToggle = useCallback((productId, extend = false) => {
    const from = pageRef.current.indexOf(anchor.current);
    const to = pageRef.current.indexOf(productId);
    setChecked((current) => {
      const next = new Set(current);
      if (extend && from !== -1 && to !== -1) {
        pageRef.current.slice(Math.min(from, to), Math.max(from, to) + 1).forEach((id) => next.add(id));
      } else if (!next.delete(productId)) next.add(productId);
      return next;
    });
    anchor.current = productId;
  }, []);

  // Shift+Up / Shift+Down: the range from the product toggled last, or only this product when that one is not on
  // show. It only checks: moving over a checked row never unchecks it.
  const extendTo = useCallback((productId) => {
    const from = pageRef.current.indexOf(anchor.current);
    const to = pageRef.current.indexOf(productId);
    setChecked((current) => {
      const next = new Set(current);
      if (from !== -1 && to !== -1) pageRef.current.slice(Math.min(from, to), Math.max(from, to) + 1).forEach((id) => next.add(id));
      else next.add(productId);
      return next;
    });
    anchor.current = productId;
  }, []);

  const pageState = useMemo(() => {
    if (page.length === 0) return 'empty';
    const on = page.filter((id) => checked.has(id)).length;
    return on === 0 ? 'none' : on === page.length ? 'all' : 'some';
  }, [page, checked]);

  const offPageCount = useMemo(() => {
    const shown = new Set(page);
    return [...checked].filter((id) => !shown.has(id)).length;
  }, [page, checked]);

  const togglePage = useCallback(() => {
    const ids = pageRef.current;
    if (ids.length === 0) return;
    setChecked((current) => {
      const next = new Set(current);
      if (ids.every((id) => current.has(id))) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setChecked(new Set());
    anchor.current = null;
  }, []);

  return { checked, onToggle, extendTo, togglePage, clear, pageState, offPageCount };
}
