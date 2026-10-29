/** The campaign form's values (strings, as the inputs hold them), to and from the API's `SellOutCampanaIn`. */

export const CAMPANA_VACIA = {
  nombre: '',
  descripcion: '',
  fechaDesde: '',
  fechaHasta: '',
  tipo: 'por_unidad',
  montoUnit: '',
  porcentaje: '',
  // `monto_total` only: the campaign's one amount, never 0 (negative: a deduction from profit, S35).
  montoTotal: '',
  basePorcentaje: 'costo',
  moneda: 'USD',
  tcModo: 'al_cobro',
  tipoCambio: '',
  topeUnidades: '',
  topeMonto: '',
  acumulable: true,
  montoIncluyeIva: false,
  grupoIds: [],
  // Products with their own amount per unit (`por_unidad` only; a `monto_total` campaign's shares are edited apart,
  // in its reparto section, so they never enter the form): `{ itemId, codigo, descripcion, monto }`.
  // The API names each stored product (`codigo`/`descripcion`); null when it left the ERP catalog.
  items: [],
};

const texto = (value) => (value === null || value === undefined ? '' : String(value));
const opcional = (value) => (String(value ?? '').trim() === '' ? null : String(value).trim());
const positivo = (value) => Number(value) > 0;
const distintoDeCero = (value) => Number.isFinite(Number(value)) && Number(value) !== 0;

/** A stored campaign (`SellOutCampanaOut`) as form values. */
export function valoresDeCampana(campana) {
  return {
    nombre: campana.nombre,
    descripcion: texto(campana.descripcion),
    fechaDesde: campana.fecha_desde,
    fechaHasta: campana.fecha_hasta,
    tipo: campana.tipo,
    montoUnit: texto(campana.monto_unit),
    porcentaje: texto(campana.porcentaje),
    montoTotal: texto(campana.monto_total),
    basePorcentaje: campana.base_porcentaje ?? 'costo',
    moneda: campana.moneda,
    tcModo: campana.tc_modo ?? 'al_cobro',
    tipoCambio: texto(campana.tipo_cambio),
    topeUnidades: texto(campana.tope_unidades),
    topeMonto: texto(campana.tope_monto),
    acumulable: campana.acumulable,
    montoIncluyeIva: campana.monto_incluye_iva,
    grupoIds: (campana.grupos ?? []).map((g) => g.id),
    items: (campana.tipo === 'monto_total' ? [] : campana.items ?? []).map((i) => ({
      itemId: i.item_id,
      codigo: i.codigo ?? null,
      descripcion: i.descripcion ?? null,
      monto: texto(i.monto_unit),
    })),
  };
}

/**
 * The request body: the amount of its type only, the FX fields only in USD (the rate only when fixed),
 * empty optionals as null. Amounts stay strings: the backend reads them as Decimal. `items` always goes (a full
 * replace): `[]` in a percentage campaign, which takes no per-product amounts. A `monto_total` campaign sends its
 * total and no caps, and no `items` (the API keeps the stored shares, set with `PUT /reparto`), except `[]` to drop
 * the per-unit amounts of a campaign switched to it.
 */
export function bodyDeCampana(v) {
  if (v.tipo === 'monto_total') {
    const { items: _items, ...comun } = bodyBase(v);
    return {
      ...comun,
      monto_unit: null,
      porcentaje: null,
      monto_total: opcional(v.montoTotal),
      tope_unidades: null,
      tope_monto: null,
      ...(v.items.length ? { items: [] } : {}),
    };
  }
  return bodyBase(v);
}

function bodyBase(v) {
  const porUnidad = v.tipo === 'por_unidad';
  const usd = v.moneda === 'USD';
  const tope = opcional(v.topeUnidades);
  return {
    nombre: v.nombre.trim(),
    descripcion: opcional(v.descripcion),
    fecha_desde: v.fechaDesde,
    fecha_hasta: v.fechaHasta,
    tipo: v.tipo,
    monto_unit: porUnidad ? opcional(v.montoUnit) : null,
    porcentaje: porUnidad ? null : opcional(v.porcentaje),
    base_porcentaje: v.basePorcentaje,
    moneda: v.moneda,
    tc_modo: usd ? v.tcModo : null,
    tipo_cambio: usd && v.tcModo === 'fijo' ? opcional(v.tipoCambio) : null,
    tope_unidades: tope === null ? null : Number(tope),
    tope_monto: opcional(v.topeMonto),
    acumulable: v.acumulable,
    monto_incluye_iva: v.montoIncluyeIva,
    grupo_ids: v.grupoIds,
    items: porUnidad ? v.items.map((i) => ({ item_id: i.itemId, monto_unit: String(i.monto).trim() })) : [],
  };
}

/** What the form still needs before it can be sent, as words for the message ("Faltan datos: …"). */
export function faltantes(v) {
  const faltan = [];
  if (!v.nombre.trim()) faltan.push('nombre');
  if (!v.fechaDesde || !v.fechaHasta) faltan.push('fechas');
  if (v.tipo === 'por_unidad' && !positivo(v.montoUnit)) faltan.push('monto por unidad');
  if (v.tipo === 'por_unidad' && v.items.some((i) => !positivo(i.monto))) faltan.push('monto de cada producto');
  if (v.tipo === 'porcentaje' && !positivo(v.porcentaje)) faltan.push('porcentaje');
  if (v.tipo === 'monto_total' && !distintoDeCero(v.montoTotal)) faltan.push('monto total');
  if (v.moneda === 'USD' && v.tcModo === 'fijo' && !positivo(v.tipoCambio)) faltan.push('tipo de cambio');
  if (opcional(v.topeUnidades) !== null && !Number.isInteger(Number(v.topeUnidades))) faltan.push('tope de unidades entero');
  if (v.grupoIds.length === 0) faltan.push('productos alcanzados');
  return faltan;
}
