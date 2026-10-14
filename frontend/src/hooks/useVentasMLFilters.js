import { useSearchParams } from 'react-router-dom';
import { useCallback, useMemo, useState } from 'react';
import { businessToday, calcularRangoPreset, currentMonthRange } from '../utils/dateRangePresets';

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A real calendar day: `2026-13-45` has the right shape and is not one. */
function isRealDay(value) {
  if (!value || !ISO_DAY.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

// Presets the date control highlights; an active range is matched against
// them so the highlight is never a claim the URL cannot back up. Month first:
// on the 14th, 14d and the month start coincide and the default must read as it is.
const PRESET_KEYS = ['mesActual', 'hoy', 'ayer', '3d', '7d', '14d', '30d', '3m'];

// The date control computes its presets from the BROWSER's day, this hook from
// Argentina's: near midnight outside UTC-3 they differ, so a click on "7d"
// must still highlight "7d". Either day matching is enough.
function presetFor(desde, hasta) {
  const days = [businessToday(), new Date()];
  return (
    PRESET_KEYS.find((key) =>
      days.some((hoy) => {
        const r = calcularRangoPreset(key, hoy);
        return r && r.desde === desde && r.hasta === hasta;
      }),
    ) ?? 'custom'
  );
}

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
 *
 * `ventas-ml-filtros-producto` adds `marcas` / `subcategorias` / `pms`
 * (and `metricas-ml-filtros-dinamicos` `categorias`),
 * same convention again: CSV params, set when non-empty, deleted (never
 * written as an empty string) when cleared — exactly the `q` pattern
 * above, not a new one.
 * PR19 (PANEL R22/R23) adds the `pack` URL param for a PACK-scoped
 * selection, mutually exclusive with `orden`: a pack row opens the pack
 * panel (`selectPack`), and picking a member order from inside that panel
 * (or a member row directly) opens the order-scoped panel (`selectOrder`).
 * Each setter clears the other param so the two never disagree about
 * what is selected.
 *
 * The DATE RANGE lives here too (`desde`/`hasta`, or `rango=todo` for an
 * explicit "no date filter"). With neither in the URL the screen opens on the
 * current month in Argentina time instead of loading every sale (~80k
 * orders); the URL always wins, so a shared link, a reload and back/forward
 * keep the range the operator was looking at. The default is computed once
 * per mount: a page left open across midnight must not shift its range under
 * the operator's feet.
 */
export function useVentasMLFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const ordenParam = searchParams.get('orden');
  const packParam = searchParams.get('pack');
  const qParam = searchParams.get('q');
  const searchQuery = qParam ?? '';

  const marcasParam = searchParams.get('marcas');
  const categoriasParam = searchParams.get('categorias');
  const subcategoriasParam = searchParams.get('subcategorias');
  const pmsParam = searchParams.get('pms');

  const desdeParam = searchParams.get('desde');
  const hastaParam = searchParams.get('hasta');
  const rangoParam = searchParams.get('rango');
  const [defaultRange] = useState(() => currentMonthRange());

  const dateRange = useMemo(() => {
    if (rangoParam === 'todo') return { desde: '', hasta: '', filtro: null };
    const desde = isRealDay(desdeParam) ? desdeParam : '';
    const hasta = isRealDay(hastaParam) ? hastaParam : '';
    if (desde || hasta) return { desde, hasta, filtro: presetFor(desde, hasta) };
    return { ...defaultRange, filtro: 'mesActual' };
  }, [desdeParam, hastaParam, rangoParam, defaultRange]);

  // True when the URL says nothing about the range, i.e. the default month.
  const dateRangeIsDefault = useMemo(
    () => rangoParam !== 'todo' && !isRealDay(desdeParam) && !isRealDay(hastaParam),
    [rangoParam, desdeParam, hastaParam],
  );

  const setDateRange = useCallback(
    ({ desde, hasta }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('desde');
          next.delete('hasta');
          next.delete('rango');
          if (desde) next.set('desde', desde);
          if (hasta) next.set('hasta', hasta);
          // Cleared: say so, or the absence would read as "use the default".
          if (!desde && !hasta) next.set('rango', 'todo');
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const productFilters = useMemo(
    () => ({
      marcas: marcasParam ? marcasParam.split(',').filter(Boolean) : [],
      categorias: categoriasParam ? categoriasParam.split(',').filter(Boolean) : [],
      subcategorias: subcategoriasParam
        ? subcategoriasParam
            .split(',')
            .map((v) => Number(v))
            .filter((v) => !Number.isNaN(v))
        : [],
      pms: pmsParam
        ? pmsParam
            .split(',')
            .map((v) => Number(v))
            .filter((v) => !Number.isNaN(v))
        : [],
    }),
    [marcasParam, categoriasParam, subcategoriasParam, pmsParam],
  );
  // Order/pack ids are numeric on this screen (`order_id`/`pack_id` from
  // ML) — parsed once here so every consumer (the panel's fetch, the
  // layout's grid) reads the same type instead of each doing its own
  // `Number(...)`.
  const selectedOrderId = useMemo(() => {
    if (ordenParam === null || ordenParam === '') return null;
    const parsed = Number(ordenParam);
    return Number.isNaN(parsed) ? null : parsed;
  }, [ordenParam]);

  const selectedPackId = useMemo(() => {
    if (packParam === null || packParam === '') return null;
    const parsed = Number(packParam);
    return Number.isNaN(parsed) ? null : parsed;
  }, [packParam]);

  const selectOrder = useCallback(
    (orderId) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('orden', String(orderId));
          next.delete('pack');
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const selectPack = useCallback(
    (packId) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('pack', String(packId));
          next.delete('orden');
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
        next.delete('pack');
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

  const setProductFilters = useCallback(
    (next) => {
      setSearchParams(
        (prev) => {
          const nextParams = new URLSearchParams(prev);
          const marcas = next.marcas || [];
          const categorias = next.categorias || [];
          const subcategorias = next.subcategorias || [];
          const pms = next.pms || [];
          if (marcas.length > 0) nextParams.set('marcas', marcas.join(','));
          else nextParams.delete('marcas');
          if (categorias.length > 0) nextParams.set('categorias', categorias.join(','));
          else nextParams.delete('categorias');
          if (subcategorias.length > 0) nextParams.set('subcategorias', subcategorias.join(','));
          else nextParams.delete('subcategorias');
          if (pms.length > 0) nextParams.set('pms', pms.join(','));
          else nextParams.delete('pms');
          return nextParams;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const clearProductFilters = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('marcas');
        next.delete('categorias');
        next.delete('subcategorias');
        next.delete('pms');
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  // "Limpiar filtros" in ONE updater. react-router's functional form does not
  // queue: every call derives from the same render-time params, so separate
  // calls (search, product filters, range) overwrite each other and the last
  // one silently resurrects what the others cleared. The range goes back to
  // its DEFAULT (current month), never to "todo": clearing filters must not be
  // a one-click way to load every sale. `rango=todo` is still honoured when a
  // link carries it.
  const clearUrlFilters = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ['q', 'marcas', 'categorias', 'subcategorias', 'pms', 'desde', 'hasta', 'rango'].forEach((key) =>
          next.delete(key),
        );
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  return {
    selectedOrderId,
    selectOrder,
    selectedPackId,
    selectPack,
    clearSelection,
    searchQuery,
    setSearchQuery,
    productFilters,
    setProductFilters,
    clearProductFilters,
    dateRange,
    dateRangeIsDefault,
    setDateRange,
    clearUrlFilters,
  };
}
