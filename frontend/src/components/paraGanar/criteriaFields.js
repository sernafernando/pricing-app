/** Criteria field defs for the PARA GANAR Criterios panel (MLA override). */

/** Keep in sync with backend CRITERIOS_DEFAULT_* in para_ganar.py */
export const SYSTEM_CRITERIA_DEFAULTS = {
  markup_min: 5,
  markup_max: 15,
  top_sellers: 5,
  precio_min: null,
  precio_max: null,
  ganar_catalogo: false,
  ignorar_internacionales: false,
  descartar_stock_residual: false,
  descartar_reputacion_baja: false,
  techo_monopolio: false,
};

export const CRITERIA_NUMBER_FIELDS = [
  { key: 'markup_min', label: 'Markup mínimo %', placeholder: 'ej. 5' },
  { key: 'markup_max', label: 'Markup máximo %', placeholder: 'ej. 15' },
  { key: 'top_sellers', label: 'TOP sellers por tipo', placeholder: 'ej. 5', integer: true },
  { key: 'precio_min', label: 'Precio mínimo', placeholder: 'sin tope' },
  { key: 'precio_max', label: 'Precio máximo', placeholder: 'sin tope' },
];

export const CRITERIA_FLAG_FIELDS = [
  { key: 'ganar_catalogo', label: 'Ganar catálogo' },
  { key: 'ignorar_internacionales', label: 'Ignorar competidores internacionales' },
  { key: 'descartar_stock_residual', label: 'Descartar stock residual' },
  { key: 'descartar_reputacion_baja', label: 'Descartar reputación baja' },
  { key: 'techo_monopolio', label: 'Techo por monopolio' },
];

export const EMPTY_CRITERIA_FORM = {
  markup_min: String(SYSTEM_CRITERIA_DEFAULTS.markup_min),
  markup_max: String(SYSTEM_CRITERIA_DEFAULTS.markup_max),
  top_sellers: String(SYSTEM_CRITERIA_DEFAULTS.top_sellers),
  precio_min: '',
  precio_max: '',
  ganar_catalogo: false,
  ignorar_internacionales: false,
  descartar_stock_residual: false,
  descartar_reputacion_baja: false,
  techo_monopolio: false,
};

export function criteriaToForm(data) {
  return {
    markup_min: data?.markup_min != null ? String(data.markup_min) : '',
    markup_max: data?.markup_max != null ? String(data.markup_max) : '',
    top_sellers: data?.top_sellers != null ? String(data.top_sellers) : '',
    precio_min: data?.precio_min != null ? String(data.precio_min) : '',
    precio_max: data?.precio_max != null ? String(data.precio_max) : '',
    ganar_catalogo: Boolean(data?.ganar_catalogo),
    ignorar_internacionales: Boolean(data?.ignorar_internacionales),
    descartar_stock_residual: Boolean(data?.descartar_stock_residual),
    descartar_reputacion_baja: Boolean(data?.descartar_reputacion_baja),
    techo_monopolio: Boolean(data?.techo_monopolio),
  };
}

function parseOptionalNumber(raw, { integer = false } = {}) {
  const trimmed = String(raw ?? '').trim();
  if (!trimmed) return null;
  const value = integer ? Number.parseInt(trimmed, 10) : Number(trimmed);
  if (Number.isNaN(value)) {
    throw new Error(`Valor numérico inválido: ${trimmed}`);
  }
  return value;
}

export function formToPayload(form) {
  return {
    markup_min: parseOptionalNumber(form.markup_min),
    markup_max: parseOptionalNumber(form.markup_max),
    top_sellers: parseOptionalNumber(form.top_sellers, { integer: true }),
    precio_min: parseOptionalNumber(form.precio_min),
    precio_max: parseOptionalNumber(form.precio_max),
    ganar_catalogo: Boolean(form.ganar_catalogo),
    ignorar_internacionales: Boolean(form.ignorar_internacionales),
    descartar_stock_residual: Boolean(form.descartar_stock_residual),
    descartar_reputacion_baja: Boolean(form.descartar_reputacion_baja),
    techo_monopolio: Boolean(form.techo_monopolio),
  };
}

export function sourceLabel(source) {
  if (source === 'mla') return 'MLA';
  if (source === 'producto') return 'producto';
  if (source === 'pm') return 'default PM';
  return 'default';
}
