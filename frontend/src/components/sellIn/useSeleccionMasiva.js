import { useCallback, useState } from 'react';

/** The ids checked in a list for a bulk action: one row, the visible page, or a whole resolved set. */
export function useSeleccionMasiva() {
  const [ids, setIds] = useState(() => new Set());
  const toggle = useCallback(
    (id) =>
      setIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    [],
  );
  // The header checkbox: checks the whole page, or unchecks it when every row of it was already checked.
  const togglePagina = useCallback(
    (pagina) =>
      setIds((prev) => {
        const todas = pagina.length > 0 && pagina.every((id) => prev.has(id));
        const next = new Set(prev);
        pagina.forEach((id) => (todas ? next.delete(id) : next.add(id)));
        return next;
      }),
    [],
  );
  const reemplazar = useCallback((lista) => setIds(new Set(lista)), []);
  const limpiar = useCallback(() => setIds(new Set()), []);
  return { ids, toggle, togglePagina, reemplazar, limpiar };
}
