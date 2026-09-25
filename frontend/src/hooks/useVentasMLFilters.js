import { useSearchParams } from 'react-router-dom';
import { useCallback, useMemo } from 'react';

/**
 * useVentasMLFilters — selection state for the `VentasML` sale detail panel
 * (ventas-ml-rediseno PR13, PANEL R19: "consistent with existing
 * filter/selection URL conventions on this screen").
 *
 * Scope for PR13 was the ROW SELECTION only (`orden` URL param), the piece
 * `VentasMLLayout`/`SaleDetailPanel` need to replace `DesgloseDrawer`'s
 * local `drawerOrderId` state.
 *
 * PR14 (SEARCH R25, R26) adds the `q` URL param for the search box, same
 * URL-state convention as `orden`: the search box is a URL-driven filter,
 * not local-only state, so a shared link or a page reload keeps the same
 * results the operator was looking at.
 */
export function useVentasMLFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const ordenParam = searchParams.get('orden');
  const qParam = searchParams.get('q');
  const searchQuery = qParam ?? '';
  // Order ids are numeric on this screen (`order_id` from ML) — parsed
  // once here so every consumer (the panel's fetch, the layout's grid)
  // reads the same type instead of each doing its own `Number(...)`.
  const selectedOrderId = useMemo(() => {
    if (ordenParam === null || ordenParam === '') return null;
    const parsed = Number(ordenParam);
    return Number.isNaN(parsed) ? null : parsed;
  }, [ordenParam]);

  const selectOrder = useCallback(
    (orderId) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('orden', String(orderId));
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const clearSelection = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('orden');
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  // Setting an empty string REMOVES the param instead of writing `q=`,
  // consistent with `clearSelection`: an empty search means "no filter",
  // not "filter by the empty string" — a bare `?q=` in a shared link would
  // otherwise read as an intentional (if odd) empty-search filter.
  const setSearchQuery = useCallback(
    (value) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set('q', value);
          else next.delete('q');
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  return {
    selectedOrderId,
    selectOrder,
    clearSelection,
    searchQuery,
    setSearchQuery,
  };
}
