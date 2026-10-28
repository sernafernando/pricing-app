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
  mlasText: '',
  tipos_publicacion: [],
  pricelist_ids: [],
  tienda_oficial_ids: [],
};

export function subscriptionToForm(row) {
  if (!row) return { ...EMPTY_PERIODICIDAD_FORM };
  return {
    enabled: row.enabled !== false,
    scope_mode: row.scope_mode || SCOPE_ALL,
    mlasText: Array.isArray(row.mlas) ? row.mlas.join(', ') : '',
    tipos_publicacion: Array.isArray(row.tipos_publicacion) ? [...row.tipos_publicacion] : [],
    pricelist_ids: Array.isArray(row.pricelist_ids) ? row.pricelist_ids.map(Number) : [],
    tienda_oficial_ids: Array.isArray(row.tienda_oficial_ids)
      ? row.tienda_oficial_ids.map(Number)
      : [],
  };
}

export function parseMlasText(text) {
  if (!text || !String(text).trim()) return [];
  const seen = new Set();
  const out = [];
  for (const part of String(text).split(/[\s,;]+/)) {
    const mla = part.trim().toUpperCase();
    if (!mla || seen.has(mla)) continue;
    seen.add(mla);
    out.push(mla);
  }
  return out;
}

/** Build PUT body; returns { ok:false, error } or { ok:true, payload }. */
export function formToPeriodicidadPayload(form) {
  const mode = form.scope_mode || SCOPE_ALL;
  const base = { enabled: Boolean(form.enabled), scope_mode: mode };

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
    const mlas = parseMlasText(form.mlasText);
    if (mlas.length === 0) {
      return { ok: false, error: 'Agregá al menos un MLA (separados por coma).' };
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

  const tipos = Array.isArray(form.tipos_publicacion) ? form.tipos_publicacion : [];
  const pricelists = Array.isArray(form.pricelist_ids) ? form.pricelist_ids.map(Number) : [];
  const tiendas = Array.isArray(form.tienda_oficial_ids)
    ? form.tienda_oficial_ids.map(Number)
    : [];
  if (tipos.length === 0 && pricelists.length === 0 && tiendas.length === 0) {
    return {
      ok: false,
      error: 'Elegí al menos un tipo, lista de precios o tienda.',
    };
  }
  return {
    ok: true,
    payload: {
      ...base,
      mlas: [],
      tipos_publicacion: tipos,
      pricelist_ids: pricelists,
      tienda_oficial_ids: tiendas,
    },
  };
}

export function scopeSummary(row) {
  if (!row) return '';
  if (row.scope_mode === SCOPE_ALL) return 'Todo el EAN';
  if (row.scope_mode === SCOPE_MLAS) {
    const n = Array.isArray(row.mlas) ? row.mlas.length : 0;
    return `${n} MLA${n === 1 ? '' : 's'}`;
  }
  const parts = [];
  if (row.tipos_publicacion?.length) parts.push(`${row.tipos_publicacion.length} tipo(s)`);
  if (row.pricelist_ids?.length) parts.push(`${row.pricelist_ids.length} lista(s)`);
  if (row.tienda_oficial_ids?.length) parts.push(`${row.tienda_oficial_ids.length} tienda(s)`);
  return parts.length ? parts.join(' · ') : 'Reglas';
}
