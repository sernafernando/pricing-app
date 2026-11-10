/**
 * Productos markup companion context (tacticals-tienda): multi-select store/channel,
 * union semantics; Todas = omit param (global resolver).
 */
import { CANALES_TACTICAL } from '../tactical/tacticalTiendas';

/** Expand picker selection to resolver contextos: [canal, store_id|null]. null = Todas. */
export function contextosDeSeleccion(todas, keys = [], grupos = []) {
  if (todas !== false) return null;
  const out = [];
  for (const key of keys) {
    if (key === 'fuera') {
      out.push(['fuera', null]);
      continue;
    }
    if (key === 'tienda_nube') {
      out.push(['tn', null]);
      continue;
    }
    const grupo = grupos.find((g) => g.value === key);
    const ids = grupo ? grupo.ids : String(key).split(',').filter(Boolean);
    for (const id of ids) out.push(['ml', Number(id)]);
  }
  return out.length ? out : null;
}

/** Query value for GET /productos `markup_contextos`, or null when Todas. */
export function serializarContextos(contextos) {
  if (!contextos || contextos.length === 0) return null;
  return contextos
    .map(([canal, storeId]) => (canal === 'ml' ? `ml:${storeId}` : canal))
    .join(',');
}

export function paramDesdeSeleccion(todas, keys, grupos) {
  return serializarContextos(contextosDeSeleccion(todas, keys, grupos));
}

/**
 * Rebuild picker state from the listing query param: a whole store group by its option, and every other store id
 * (part of a group, or in none) as its own key, so the rebuilt selection asks for the same stores.
 */
export function seleccionDesdeParam(param, grupos = []) {
  if (!param) return { todas: true, keys: [] };
  const keys = [];
  const storeIds = new Set();
  for (const token of String(param).split(',')) {
    const tok = token.trim();
    if (tok === 'fuera') keys.push('fuera');
    else if (tok === 'tn') keys.push('tienda_nube');
    else if (tok.startsWith('ml:')) storeIds.add(tok.slice(3));
  }
  const cubiertos = new Set();
  for (const grupo of grupos) {
    if (grupo.ids.every((id) => storeIds.has(String(id)))) {
      keys.push(grupo.value);
      for (const id of grupo.ids) cubiertos.add(String(id));
    }
  }
  for (const id of storeIds) if (!cubiertos.has(id)) keys.push(id);
  return { todas: false, keys: [...new Set(keys)] };
}

export { CANALES_TACTICAL };
