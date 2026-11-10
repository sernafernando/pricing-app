/**
 * Official-store / channel scope for Nuevo tactical (tacticals-tienda).
 * Groups by `clave` expand to every store_id; channels are synthetic targets.
 */

/**
 * The store picker, the shared-cap toggle and their preview are shown, and the scope sent, only once the sell out and
 * sell in engines honour it (tacticals-tienda T3/T4). Until then a new tactical omits the scope and the API gives it
 * today's reach, so merging the UI alone never saves a scope nothing applies.
 */
export const ALCANCE_POR_TIENDA = false;

export const CANALES_TACTICAL = [
  { value: 'fuera', label: 'Por fuera' },
  { value: 'tienda_nube', label: 'Tienda Nube' },
];

export const esCanal = (key) => CANALES_TACTICAL.some((c) => c.value === key);

/** Payload `tiendas[]` for POST /tacticals from the form selection. */
export function tiendasDelContrato(todasTiendas, seleccionKeys, grupos = []) {
  const tiendas = [];
  if (!todasTiendas) {
    for (const key of seleccionKeys) {
      if (esCanal(key)) continue;
      const grupo = grupos.find((g) => g.value === key);
      const ids = grupo ? grupo.ids : String(key).split(',').filter(Boolean);
      for (const id of ids) {
        tiendas.push({ tipo: 'oficial', store_id: Number(id) });
      }
    }
  }
  for (const key of seleccionKeys) {
    if (esCanal(key)) tiendas.push({ tipo: key, store_id: null });
  }
  return tiendas;
}

/**
 * Form selection keys from a tactical detail (renovar). A saved store no whole group covers (its clave group changed,
 * or the store list failed to load) stays as its own key, so renewing never narrows the scope behind the user's back.
 */
export function seleccionDesdeDetalle(tactical, grupos = []) {
  const keys = [];
  const storeIds = (tactical.tiendas ?? [])
    .filter((t) => t.tipo === 'oficial' && t.store_id != null)
    .map((t) => String(t.store_id));
  const cubiertos = new Set();
  for (const grupo of grupos) {
    if (grupo.ids.length > 0 && grupo.ids.every((id) => storeIds.includes(id))) {
      keys.push(grupo.value);
      grupo.ids.forEach((id) => cubiertos.add(id));
    }
  }
  for (const id of storeIds) {
    if (!cubiertos.has(id)) keys.push(id);
  }
  for (const fila of tactical.tiendas ?? []) {
    if (fila.tipo === 'fuera' || fila.tipo === 'tienda_nube') keys.push(fila.tipo);
  }
  return keys;
}

const idsDe = (key, grupos) => grupos.find((g) => g.value === key)?.ids ?? String(key).split(',').filter(Boolean);
const idsDeTodas = (grupos) => grupos.reduce((n, g) => n + g.ids.length, 0);

/**
 * How many cap counters a capped line gets, as the engines split it: one with a shared cap (or while the store scope
 * is off: the API then gives today's shared reach); per store otherwise, one per official store id (plus the ML sales
 * without a store, with every store) and one per channel.
 */
export function contadoresDelTope({ todasTiendas, seleccionKeys, grupos = [], topeCompartido, alcancePorTienda = ALCANCE_POR_TIENDA }) {
  if (!alcancePorTienda || topeCompartido) return 1;
  const canales = seleccionKeys.filter(esCanal).length;
  const oficiales = todasTiendas
    ? idsDeTodas(grupos) + 1
    : seleccionKeys.filter((k) => !esCanal(k)).reduce((n, k) => n + idsDe(k, grupos).length, 0);
  return Math.max(oficiales + canales, 1);
}

/**
 * Live preview rows for how the line cap applies to the current selection.
 * `ejemploTope` is the number shown (first line unit cap), or null → "tope".
 */
export function previewTope({ todasTiendas, seleccionKeys, grupos = [], topeCompartido, ejemploTope }) {
  const n = ejemploTope == null || ejemploTope === '' ? 'tope' : String(ejemploTope);
  const labels = [];
  if (todasTiendas) {
    labels.push('Todas las tiendas oficiales');
  } else {
    for (const key of seleccionKeys) {
      if (esCanal(key)) continue;
      const grupo = grupos.find((g) => g.value === key);
      labels.push(grupo ? grupo.label : `Tienda ${key}`);
    }
  }
  for (const key of seleccionKeys) {
    if (!esCanal(key)) continue;
    labels.push(CANALES_TACTICAL.find((c) => c.value === key)?.label ?? key);
  }
  if (labels.length === 0) {
    return { modo: topeCompartido ? 'compartido' : 'por_tienda', filas: [], ayuda: 'Elegí al menos una tienda o canal.' };
  }
  if (topeCompartido) {
    return {
      modo: 'compartido',
      filas: [{ label: labels.join(' + '), valor: `${n} compartidos` }],
      ayuda: '1 venta en cualquiera resta del mismo pool.',
    };
  }
  const filas = [];
  if (todasTiendas) {
    filas.push({ label: `Cada tienda oficial (${idsDeTodas(grupos)})`, valor: `${n} cada una` });
    filas.push({ label: 'Ventas sin tienda oficial', valor: String(n) });
  } else {
    for (const key of seleccionKeys) {
      if (esCanal(key)) continue;
      const grupo = grupos.find((g) => g.value === key);
      const ids = idsDe(key, grupos);
      const label = grupo ? grupo.label : `Tienda ${key}`;
      filas.push(ids.length > 1 ? { label: `${label} (${ids.length} tiendas)`, valor: `${n} cada una` } : { label, valor: String(n) });
    }
  }
  for (const key of seleccionKeys) {
    if (esCanal(key)) filas.push({ label: CANALES_TACTICAL.find((c) => c.value === key)?.label ?? key, valor: String(n) });
  }
  return {
    modo: 'por_tienda',
    filas,
    ayuda: 'Cada tienda o canal tiene su propio contador con el mismo tope.',
  };
}
