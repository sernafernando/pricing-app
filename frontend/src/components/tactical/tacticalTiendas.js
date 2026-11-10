/**
 * Official-store / channel scope for Nuevo tactical (tacticals-tienda).
 * Groups by `clave` expand to every store_id; channels are synthetic targets.
 */

/**
 * The store picker, the shared-cap toggle and their preview are shown, and the scope sent, only once the sell out and
 * sell in engines honour it (tacticals-tienda T3/T4, both in). Off, a new tactical omits the scope and the API gives it
 * today's reach.
 */
export const ALCANCE_POR_TIENDA = true;

/**
 * A new tactical's scope: today's reach (every ML sale, with or without an official store, outside sales and Tienda
 * Nube, one shared cap), as an existing one got. Narrowing stores and per-store caps are the user's choice.
 */
export const ALCANCE_INICIAL = { todasTiendas: true, topeCompartido: true, tiendaKeys: ['fuera', 'tienda_nube'] };

export const CANALES_TACTICAL = [
  { value: 'fuera', label: 'Por fuera' },
  { value: 'tienda_nube', label: 'Tienda Nube' },
];

export const esCanal = (key) => CANALES_TACTICAL.some((c) => c.value === key);

// "Todas las tiendas oficiales" is every sale of every channel (S2, owner 2026-11-10: "es todas las ventas de ese
// producto"): it reaches each channel whatever the selection says, and the server stores it as all, with no row.
const canalesDe = (todasTiendas, seleccionKeys) =>
  todasTiendas ? CANALES_TACTICAL.map((c) => c.value) : seleccionKeys.filter(esCanal);
const nombreCanal = (key) => CANALES_TACTICAL.find((c) => c.value === key)?.label ?? key;

/** Payload `tiendas[]` for POST /tacticals from the form selection. */
export function tiendasDelContrato(todasTiendas, seleccionKeys, grupos = []) {
  const tiendas = [];
  if (todasTiendas) return tiendas;
  for (const key of seleccionKeys) {
    if (esCanal(key)) continue;
    const grupo = grupos.find((g) => g.value === key);
    const ids = grupo ? grupo.ids : String(key).split(',').filter(Boolean);
    for (const id of ids) {
      tiendas.push({ tipo: 'oficial', store_id: Number(id) });
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
// With every store, the engines start one counter per ACTIVE official store (`tienda_scope.contadores`); a group's ids
// also hold the inactive stores of its clave, so the caller passes the active count when it has it.
const idsDeTodas = (grupos, tiendasActivas) => tiendasActivas ?? grupos.reduce((n, g) => n + g.ids.length, 0);

/**
 * How many cap counters a capped line gets, as the engines split it: one with a shared cap (or while the store scope
 * is off: the API then gives today's shared reach); per store otherwise, one per official store id (plus the ML sales
 * without a store, with every store) and one per channel.
 */
export function contadoresDelTope({
  todasTiendas,
  seleccionKeys,
  grupos = [],
  tiendasActivas,
  topeCompartido,
  alcancePorTienda = ALCANCE_POR_TIENDA,
}) {
  if (!alcancePorTienda || topeCompartido) return 1;
  const canales = canalesDe(todasTiendas, seleccionKeys).length;
  const oficiales = todasTiendas
    ? idsDeTodas(grupos, tiendasActivas) + 1
    : seleccionKeys.filter((k) => !esCanal(k)).reduce((n, k) => n + idsDe(k, grupos).length, 0);
  return Math.max(oficiales + canales, 1);
}

const TITULO_COMPARTIDO = 'Un solo tope entre todas';
const TITULO_POR_TIENDA = 'Un tope para cada tienda o canal';

/**
 * Live preview of what the line cap does with the current selection (owner, 2026-11-10: "«Cómo se aplica el tope» no
 * se entiende"): a title naming the mode, one row per counter and a sentence saying when crediting stops.
 * `ejemploTope` is the first line unit cap, shown as "100 u."; null speaks of "the line cap" instead.
 */
export function previewTope({ todasTiendas, seleccionKeys, grupos = [], tiendasActivas, topeCompartido, ejemploTope }) {
  const conTope = !(ejemploTope == null || ejemploTope === '');
  const unidades = conTope
    ? `${Number.isFinite(Number(ejemploTope)) ? Number(ejemploTope).toLocaleString('es-AR') : ejemploTope} u.`
    : null;
  const uno = unidades ?? 'tope de la línea';
  const cadaUna = unidades ? `${unidades} cada una` : 'tope de la línea, cada una';
  const titulo = topeCompartido ? TITULO_COMPARTIDO : TITULO_POR_TIENDA;
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
  if (!todasTiendas) labels.push(...seleccionKeys.filter(esCanal).map(nombreCanal));
  if (labels.length === 0) {
    return { modo: topeCompartido ? 'compartido' : 'por_tienda', titulo, filas: [], ayuda: 'Elegí al menos una tienda o canal.' };
  }
  if (topeCompartido) {
    return {
      modo: 'compartido',
      titulo,
      filas: [{ label: labels.join(' + '), valor: unidades ? `${unidades} en total` : 'tope de la línea, en total' }],
      ayuda: unidades
        ? `Las ventas de todas suman al mismo tope: cuando se vendan ${unidades} en total, deja de acreditar en todas.`
        : 'Las ventas de todas suman al mismo tope: cuando juntas llegan al tope de la línea, deja de acreditar en todas.',
    };
  }
  const filas = [];
  if (todasTiendas) {
    filas.push({ label: `Cada tienda oficial (${idsDeTodas(grupos, tiendasActivas)})`, valor: cadaUna });
    filas.push({ label: 'Ventas sin tienda oficial', valor: uno });
  } else {
    for (const key of seleccionKeys) {
      if (esCanal(key)) continue;
      const grupo = grupos.find((g) => g.value === key);
      const ids = idsDe(key, grupos);
      const label = grupo ? grupo.label : `Tienda ${key}`;
      filas.push(ids.length > 1 ? { label: `${label} (${ids.length} tiendas)`, valor: cadaUna } : { label, valor: uno });
    }
  }
  for (const key of canalesDe(todasTiendas, seleccionKeys)) filas.push({ label: nombreCanal(key), valor: uno });
  return {
    modo: 'por_tienda',
    titulo,
    filas,
    ayuda: unidades
      ? `Cada una cuenta sus ventas aparte: cuando una llega a ${unidades} vendidas, deja de acreditar solo en esa y las demás siguen hasta sus propias ${unidades}`
      : 'Cada una cuenta sus ventas aparte: cuando una llega al tope de la línea, deja de acreditar solo en esa y las demás siguen.',
  };
}
