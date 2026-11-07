/**
 * Official-store / channel scope for Nuevo tactical (tacticals-tienda).
 * Groups by `clave` expand to every store_id; channels are synthetic targets.
 */

export const CANALES_TACTICAL = [
  { value: 'fuera', label: 'Por fuera' },
  { value: 'tienda_nube', label: 'Tienda Nube' },
];

const esCanal = (key) => CANALES_TACTICAL.some((c) => c.value === key);

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

/** Form selection keys from a tactical detail (renovar). */
export function seleccionDesdeDetalle(tactical, grupos = []) {
  const keys = [];
  const storeIds = (tactical.tiendas ?? [])
    .filter((t) => t.tipo === 'oficial' && t.store_id != null)
    .map((t) => String(t.store_id));
  for (const grupo of grupos) {
    if (grupo.ids.every((id) => storeIds.includes(id))) {
      keys.push(grupo.value);
    }
  }
  for (const fila of tactical.tiendas ?? []) {
    if (fila.tipo === 'fuera' || fila.tipo === 'tienda_nube') keys.push(fila.tipo);
  }
  return keys;
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
  return {
    modo: 'por_tienda',
    filas: labels.map((label) => ({ label, valor: String(n) })),
    ayuda: 'Cada tienda o canal tiene su propio contador con el mismo tope.',
  };
}
