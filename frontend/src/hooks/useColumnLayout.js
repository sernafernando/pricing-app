import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { mlPublicationsPresetsAPI } from '../services/mlPublicationsPresets';
import {
  layoutMatches,
  layoutPayload,
  resolveOrder,
  resolveVisibility,
  sanitizeLayout,
} from '../components/publicacionesMl/presets/columnLayout';

/**
 * The column layout of each Publicaciones ML view, per user and on the server (pubml-columnas-presets S1, S2): which
 * columns show and in which order, plus the preset last applied (`preset_activo_id`).
 *
 * Split in two because the page needs the stored state long before it knows its columns (the remembered preset may
 * change the URL before the rows are asked): `useLayoutStore(vista)` loads and saves, `layoutView(store, columns,
 * defaults)` reads it over the columns the view has right now. `useColumnLayout` is both at once.
 */

// A burst of picker clicks is one save.
export const SAVE_DELAY_MS = 600;

// Before the server kept it, the Auditoría view remembered its hidden columns in this browser (auditoria-stock L6):
// with nothing on the server, that is where the user left it.
const AUDIT_LEGACY_KEY = 'publicaciones-ml.auditoria.columnas-ocultas';

function legacySeed(vista) {
  if (vista !== 'auditoria') return null;
  try {
    const hidden = JSON.parse(localStorage.getItem(AUDIT_LEGACY_KEY));
    if (!Array.isArray(hidden) || hidden.length === 0) return null;
    return sanitizeLayout({ visibility: Object.fromEntries(hidden.map((key) => [key, false])), order: [] });
  } catch {
    return null;
  }
}

const NOT_LOADED = { columns: null, presetId: null, loaded: false };

/**
 * `{ loaded, columns, presetId, save(columns, presetId, { immediate, persist }) }` of `vista`. `save` shows at once
 * and is written after `SAVE_DELAY_MS` (right away with `immediate`; never with `persist: false`); a save still
 * waiting goes to its own view when the view changes or the page closes. A failed load or save is no error on
 * screen: the view shows its defaults, or the choice lasts until the reload.
 */
export function useLayoutStore(vista) {
  const [state, setState] = useState({ vista: null, ...NOT_LOADED });
  const pending = useRef(null);

  const flush = useCallback(() => {
    const waiting = pending.current;
    if (!waiting) return;
    clearTimeout(waiting.timer);
    pending.current = null;
    mlPublicationsPresetsAPI.saveLayout(waiting.vista, waiting.body).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    mlPublicationsPresetsAPI
      .getLayout(vista)
      .then((data) => {
        if (cancelled) return;
        const presetId = Number.isInteger(data?.preset_activo_id) ? data.preset_activo_id : null;
        setState({ vista, columns: sanitizeLayout(data?.columns) ?? legacySeed(vista), presetId, loaded: true });
      })
      .catch(() => {
        if (!cancelled) setState({ vista, columns: legacySeed(vista), presetId: null, loaded: true });
      });
    return () => {
      cancelled = true;
      flush();
    };
  }, [vista, flush]);

  const save = useCallback(
    (columns, presetId, { immediate = false, persist = true } = {}) => {
      setState({ vista, columns, presetId, loaded: true });
      if (!persist) return;
      if (pending.current) clearTimeout(pending.current.timer);
      pending.current = { vista, body: { columns, preset_activo_id: presetId }, timer: setTimeout(flush, SAVE_DELAY_MS) };
      if (immediate) flush();
    },
    [vista, flush],
  );

  const current = state.vista === vista ? state : NOT_LOADED;
  const { loaded, columns, presetId } = current;
  // Stable while nothing changes, so what is read over it can be memoized.
  return useMemo(() => ({ vista, loaded, columns, presetId, save }), [vista, loaded, columns, presetId, save]);
}

/**
 * The store read over `columns` (the view's, in default order, each `{ key, group?, label?, header? }`; the first one
 * is fixed): the effective `visibility` and `order`, `arrange(cols)` (the visible ones in order), the kit
 * ColumnPicker's `pickerTable`, and the writes `reorder`, `reset`, `applyLayout`, `setPresetId`. `current` is the
 * layout as a preset saves it; `matches(saved)` whether a saved layout shows exactly what is on screen.
 */
export function layoutView(store, columns, defaults = {}) {
  const saved = store.columns;
  const visibility = resolveVisibility(columns, defaults, saved?.visibility);
  const order = resolveOrder(columns, saved?.order);
  const fixedKey = columns[0]?.key;
  const current = layoutPayload(saved, visibility, order);
  const byKey = new Map(columns.map((column) => [column.key, column]));

  const write = (nextVisibility, nextOrder) => store.save(layoutPayload(saved, nextVisibility, nextOrder), store.presetId);
  const toggle = (key) => write({ ...visibility, [key]: !visibility[key] }, order);

  const arrange = (cols) => {
    const own = new Map(cols.map((column) => [column.key, column]));
    return resolveOrder(cols, order)
      .map((key) => own.get(key))
      .filter((column) => visibility[column.key] !== false);
  };

  const pickerTable = {
    getAllLeafColumns: () =>
      order.map((key) => {
        const column = byKey.get(key);
        return {
          id: key,
          columnDef: { header: column.label ?? column.header ?? key, meta: { group: column.group ?? null } },
          getCanHide: () => key !== fixedKey,
          getIsVisible: () => visibility[key] !== false,
          getToggleVisibilityHandler: () => () => toggle(key),
        };
      }),
  };

  // `ids` are the picker's columns in their new order; the fixed one stays first, anything else after them.
  const reorder = (ids) => {
    const moved = ids.filter((id) => byKey.has(id) && id !== fixedKey);
    write(visibility, [fixedKey, ...moved, ...order.filter((key) => key !== fixedKey && !moved.includes(key))]);
  };

  return {
    loaded: store.loaded,
    presetId: store.presetId,
    visibility,
    order,
    current,
    arrange,
    pickerTable,
    reorder,
    // "Restablecer": the view's defaults and no preset, saved right away.
    reset: () => store.save(null, null, { immediate: true }),
    applyLayout: (layout, presetId) => store.save(sanitizeLayout(layout), presetId),
    setPresetId: (presetId) => store.save(saved, presetId),
    matches: (layout) => layoutMatches(columns, defaults, layout, visibility, order),
  };
}

/** `useLayoutStore` and `layoutView` together, for a caller that knows its columns from the start. */
export default function useColumnLayout({ vista, columns, defaults }) {
  return layoutView(useLayoutStore(vista), columns, defaults);
}
