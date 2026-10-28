/** Helpers for PARA GANAR Periodicidad subscription forms (P3). */

export const SCOPE_ALL = 'all';
export const SCOPE_MLAS = 'mlas';
export const SCOPE_RULES = 'rules';

export const TIPO_OPCIONES = [
  { id: 'clasica', nombre: 'Clásica' },
  { id: '3', nombre: '3 cuotas' },
  { id: '6', nombre: '6 cuotas' },
  { id: '9', nombre: '9 cuotas' },
  { id: '12', nombre: '12 cuotas' },
];

export const EMPTY_PERIODICIDAD_FORM = {
  enabled: true,
  scope_mode: SCOPE_ALL,
  mlas: [],
  tipos_publicacion: [],
  pricelist_ids: [],
  tienda_oficial_ids: [],
};

export function subscriptionToForm(row) {
  if (!row) return { ...EMPTY_PERIODICIDAD_FORM, mlas: [] };
  return {
    enabled: row.enabled !== false,
    scope_mode: row.scope_mode || SCOPE_ALL,
    mlas: Array.isArray(row.mlas) ? [...row.mlas] : [],
    tipos_publicacion: Array.isArray(row.tipos_publicacion) ? [...row.tipos_publicacion] : [],
    pricelist_ids: Array.isArray(row.pricelist_ids) ? row.pricelist_ids.map(Number) : [],
    tienda_oficial_ids: Array.isArray(row.tienda_oficial_ids)
      ? row.tienda_oficial_ids.map(Number)
      : [],
  };
}

/** Build PUT body; returns { ok:false, error } or { ok:true, payload }. */
export function formToPeriodicidadPayload(form) {
  const mode = form.scope_mode || SCOPE_ALL;
  const base = { enabled: Boolean(form.enabled), scope_mode: mode };
  const mlas = Array.isArray(form.mlas)
    ? [...new Set(form.mlas.map((m) => String(m).trim().toUpperCase()).filter(Boolean))]
    : [];

  if (mode === SCOPE_ALL) {
    return {
      ok: true,
      payload: {
        ...base,
        mlas: [],
        tipos_publicacion: [],
        pricelist_ids: [],
        tienda_oficial_ids: [],
      },
    };
  }

  if (mode === SCOPE_MLAS) {
    if (mlas.length === 0) {
      return { ok: false, error: 'Seleccioná al menos un MLA del listado.' };
    }
    return {
      ok: true,
      payload: {
        ...base,
        mlas,
        tipos_publicacion: [],
        pricelist_ids: [],
        tienda_oficial_ids: [],
      },
    };
  }

  // rules no longer offered in UI (P3.2); keep API for legacy rows until migrated.
  if (mode === SCOPE_RULES) {
    return {
      ok: false,
      error: 'Migrá la suscripción: activá Todo el EAN o tildá MLAs y guardá.',
    };
  }

  return { ok: false, error: 'Alcance inválido.' };
}

export function scopeSummary(row) {
  if (!row) return '';
  if (row.scope_mode === SCOPE_ALL) return 'Todo el EAN';
  if (row.scope_mode === SCOPE_MLAS) {
    const n = Array.isArray(row.mlas) ? row.mlas.length : row.mla_count || 0;
    return `${n} MLA${n === 1 ? '' : 's'}`;
  }
  if (row.scope_mode === SCOPE_RULES) {
    const parts = [];
    if (row.tipos_publicacion?.length) parts.push(`${row.tipos_publicacion.length} tipo(s)`);
    if (row.pricelist_ids?.length) parts.push(`${row.pricelist_ids.length} lista(s)`);
    if (row.tienda_oficial_ids?.length) parts.push(`${row.tienda_oficial_ids.length} tienda(s)`);
    return parts.length ? parts.join(' · ') : 'Reglas';
  }
  // Catalog browse rows (no subscription scope_mode): show MLA count in filter.
  if (typeof row.mla_count === 'number') {
    return `${row.mla_count} MLA${row.mla_count === 1 ? '' : 's'}`;
  }
  if (row.suscripto === false) return 'Sin suscribir';
  return '';
}
