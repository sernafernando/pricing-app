import { useSearchParams } from 'react-router-dom';
import { useCallback, useMemo } from 'react';

/**
 * useVentasMLFilters — selection state for the `VentasML` sale detail panel
 * (ventas-ml-rediseno PR13, PANEL R19: "consistent with existing
 * filter/selection URL conventions on this screen").
 *
 * Scope for PR13 is the ROW SELECTION only (`orden` URL param), the piece
 * `VentasMLLayout`/`SaleDetailPanel` need to replace `DesgloseDrawer`'s
 * local `drawerOrderId` state. Later PRs (search, chips) extend this same
 * hook with the rest of the screen's filters — see design D14.
 */
export function useVentasMLFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const ordenParam = searchParams.get('orden');
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

  return { selectedOrderId, selectOrder, clearSelection };
}
