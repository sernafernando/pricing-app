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
  // The tactical it is a line of (`tactical_id`), read-only: its own hidden group is never listed, so it needs no
  // visible group and the API keeps the hidden one on edit.
  tacticalId: null,
  // Products with their own amount per unit (`por_unidad` only; a `monto_total` campaign's shares are edited apart,
  // in its reparto section, so they never enter the form): `{ itemId, codigo, descripcion, monto }`.
  // The API names each stored product (`codigo`/`descripcion`); null when it left the ERP catalog.
  items: [],
  // How many shares a stored `monto_total` campaign has: they never enter the form, so a kind change must not send
  // `items` over them (the API refuses it: "quitá el reparto para cambiarla").
  repartosGuardados: 0,
  // A renewal (`GET /{id}/renovacion`) only: the original's program and `monto_total` shares, sent with the create
  // so the copy is saved in one call (`[{ item_id, reparto_porcentaje, reparto_monto }]`).
  programaId: null,
  renovadaDeId: null, // the campaign a renewal draft renews (`renovada_de_id`), sent only on create
  repartosCopiados: [],
  // A renewal of a campaign split by criterion (`iguales` | `unidades` | `costo`): it copies no shares and is sent
  // with the create, so the copy splits again. null: split by hand (or not a renewal); never sent on an edit.
  repartoCriterio: null,
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
    tacticalId: campana.tactical_id ?? null,
    repartosGuardados: campana.tipo === 'monto_total' ? (campana.items ?? []).length : 0,
    items: (campana.tipo === 'monto_total' ? [] : campana.items ?? []).map((i) => ({
      itemId: i.item_id,
      codigo: i.codigo ?? null,
      descripcion: i.descripcion ?? null,
      monto: texto(i.monto_unit),
    })),
  };
}

/**
 * A renewal draft (`SellOutCampanaIn`, from `GET /{id}/renovacion`) as the values of a NEW campaign. `original` is
 * the stored campaign it copies, which names its products (`codigo`/`descripcion`) for the per-unit amounts.
 */
export function valoresDeBorrador(borrador, original) {
  const productos = new Map((original?.items ?? []).map((i) => [i.item_id, i]));
  const montoTotal = borrador.tipo === 'monto_total';
  return {
    ...valoresDeCampana({ ...borrador, grupos: borrador.grupo_ids.map((id) => ({ id })), items: [] }),
    repartosGuardados: 0,
    items: montoTotal
      ? []
      : borrador.items.map((i) => ({
          itemId: i.item_id,
          codigo: productos.get(i.item_id)?.codigo ?? null,
          descripcion: productos.get(i.item_id)?.descripcion ?? null,
          monto: texto(i.monto_unit),
        })),
    repartosCopiados: montoTotal
      ? borrador.items.map((i) => ({ item_id: i.item_id, reparto_porcentaje: i.reparto_porcentaje, reparto_monto: i.reparto_monto }))
      : [],
    programaId: borrador.programa_id ?? null,
    renovadaDeId: borrador.renovada_de_id ?? null,
    repartoCriterio: montoTotal ? borrador.reparto_criterio ?? null : null,
  };
}

/**
 * The request body: the amount of its type only, the FX fields only in USD (the rate only when fixed),
 * empty optionals as null. Amounts stay strings: the backend reads them as Decimal. `items` always goes (a full
 * replace): `[]` in a percentage campaign, which takes no per-product amounts. A `monto_total` campaign sends its
 * total and no caps, and no `items` (the API keeps the stored shares, set with `PUT /reparto`), except `[]` to drop
 * the per-unit amounts of a campaign switched to it. A renewal also sends its copied shares, its program
 * (`programa_id`, only when it has one) and the campaign it renews (`renovada_de_id`), and a `monto_total` renewal
 * split by criterion its `reparto_criterio` (no shares); an edit sends none of them.
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
      ...(v.repartosCopiados?.length ? { items: v.repartosCopiados } : {}),
      ...(v.repartoCriterio ? { reparto_criterio: v.repartoCriterio } : {}),
      ...programa(v),
    };
  }
  const body = bodyBase(v);
  if (v.repartosGuardados > 0) {
    // Leaving `monto_total` with stored shares: no `items`, so the API keeps them and answers its own guard.
    const { items: _items, ...sinItems } = body;
    return sinItems;
  }
  return { ...body, ...programa(v) };
}

const programa = (v) => ({
  ...(v.programaId != null ? { programa_id: v.programaId } : {}),
  ...(v.renovadaDeId != null ? { renovada_de_id: v.renovadaDeId } : {}),
});

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
  if (v.grupoIds.length === 0 && (v.tacticalId ?? null) === null) faltan.push('productos alcanzados');
  return faltan;
}
