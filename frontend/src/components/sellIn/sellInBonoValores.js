/**
 * Form values of a bonus and the API body built from them (`SellInBonoIn`).
 *
 * A bonus reaches a brand, a category, some models or one Compras operation (`alcance`) and pays an
 * amount per invoiced unit or a % of the invoiced net (`tipo`); the body carries only the fields of its
 * scope and kind, since the backend refuses the others.
 */

export const BONO_VACIO = {
  alcance: 'marca',
  marca: '',
  categoria: '',
  // [{ itemId, label, montoUnit, porcentaje }]: a model's own value of each kind, '' when it uses the bonus's.
  // Both are kept so switching the kind back restores them; only the bonus's kind is sent.
  modelos: [],
  pedido: null, // { id, numero }
  tipo: 'por_unidad',
  montoUnit: '',
  porcentaje: '',
  moneda: 'USD',
  fechaDesde: '',
  fechaHasta: '',
  descripcion: '',
  // One cap shared by every product and purchase of the bonus (T24): invoiced units and/or money in its currency;
  // '' is no cap.
  topeUnidades: '',
  topeMonto: '',
  // The money cap as stored, with its currency (null on a new bonus): the form brings it back when the currency
  // returns to it. Never sent.
  topeGuardado: null,
};

/** The label of a model chip: code and description, or the bare item when the catalog lost it. */
export const etiquetaModelo = (modelo) => (modelo.codigo ? `${modelo.codigo} · ${modelo.descripcion}` : `Item ${modelo.item_id}`);

const texto = (value) => (value != null ? String(Number(value)) : '');

/** The form values of a bonus as the API answered it. */
export const valoresDeBono = (bono) => ({
  alcance: bono.alcance ?? 'marca',
  marca: bono.marca ?? '',
  categoria: bono.categoria ?? '',
  modelos: (bono.modelos ?? []).map((m) => ({ itemId: m.item_id, label: etiquetaModelo(m), montoUnit: texto(m.monto_unit), porcentaje: texto(m.porcentaje) })),
  pedido: bono.pedido_id ? { id: bono.pedido_id, numero: bono.pedido_numero ?? String(bono.pedido_id) } : null,
  tipo: bono.tipo ?? 'por_unidad',
  montoUnit: texto(bono.monto_unit),
  porcentaje: texto(bono.porcentaje),
  moneda: bono.moneda,
  fechaDesde: bono.fecha_desde,
  fechaHasta: bono.fecha_hasta,
  descripcion: bono.descripcion ?? '',
  topeUnidades: bono.tope_unidades != null ? String(bono.tope_unidades) : '',
  topeMonto: texto(bono.tope_monto),
  topeGuardado: { moneda: bono.moneda, monto: texto(bono.tope_monto) },
});

/** The key of the bonus's kind in the API and in a model's form values. */
const CAMPO_DEL_TIPO = { por_unidad: ['monto_unit', 'montoUnit'], porcentaje: ['porcentaje', 'porcentaje'] };

/** A model's own value of the bonus's kind, trimmed; '' when it uses the bonus's. */
export const valorDeModelo = (modelo, tipo) => String(modelo[CAMPO_DEL_TIPO[tipo][1]] ?? '').trim();

/** The models with a value of the other kind, which the body leaves out (the backend refuses them). */
export const modelosConOtroTipo = (v) => v.modelos.filter((m) => valorDeModelo(m, v.tipo === 'porcentaje' ? 'por_unidad' : 'porcentaje') !== '');

/** A model as an object (authoritative on the backend): its value of the bonus's kind, none to use the bonus's. */
const modeloDelBody = (modelo, tipo) => {
  const valor = valorDeModelo(modelo, tipo);
  return valor === '' ? { item_id: modelo.itemId } : { item_id: modelo.itemId, [CAMPO_DEL_TIPO[tipo][0]]: valor };
};

const CAMPO_DEL_ALCANCE = {
  marca: (v) => ({ marca: v.marca }),
  categoria: (v) => ({ categoria: v.categoria }),
  modelos: (v) => ({ modelos: v.modelos.map((m) => modeloDelBody(m, v.tipo)) }),
  factura: (v) => ({ pedido_id: v.pedido?.id ?? null }),
};

/**
 * The values after a currency change: the money cap is in the bonus's currency, so moving to another one empties it
 * (to be entered again there), and coming back to the stored currency brings the stored cap back, so a round trip
 * never drops it.
 */
export const conMoneda = (valores, moneda) => {
  if (moneda === valores.moneda) return valores;
  const guardado = valores.topeGuardado;
  return { ...valores, moneda, topeMonto: guardado && guardado.moneda === moneda ? guardado.monto : '' };
};

/** A cap field as sent: trimmed, or null when empty (empty means no cap). */
const normalizarTope = (valor) => String(valor ?? '').trim() || null;

/** The create/edit body (`SellInBonoIn`): a full replace on edit; an empty cap is sent as null (no cap). */
export const bodyDeBono = (valores) => ({
  alcance: valores.alcance,
  ...CAMPO_DEL_ALCANCE[valores.alcance](valores),
  tipo: valores.tipo,
  ...(valores.tipo === 'porcentaje' ? { porcentaje: valores.porcentaje } : { monto_unit: valores.montoUnit }),
  moneda: valores.moneda,
  fecha_desde: valores.fechaDesde,
  fecha_hasta: valores.fechaHasta,
  descripcion: valores.descripcion.trim() || null,
  tope_unidades: normalizarTope(valores.topeUnidades),
  tope_monto: normalizarTope(valores.topeMonto),
});

const ALCANCE_COMPLETO = {
  marca: (v) => Boolean(v.marca),
  categoria: (v) => Boolean(v.categoria),
  modelos: (v) => v.modelos.length > 0,
  factura: (v) => Boolean(v.pedido),
};

/** Whether the form has everything a bonus needs; the backend still validates the rest. */
export const bonoCompleto = (v) => {
  const monto = v.tipo === 'porcentaje' ? Number(v.porcentaje) > 0 : Number(v.montoUnit) > 0;
  return ALCANCE_COMPLETO[v.alcance](v) && monto && Boolean(v.fechaDesde && v.fechaHasta);
};

/** Why a model's own value cannot be saved (zero or less, a percentage over 100), or null. */
export const errorDeModelos = (v) => {
  if (v.alcance !== 'modelos') return null;
  const porcentaje = v.tipo === 'porcentaje';
  for (const modelo of v.modelos) {
    const valor = valorDeModelo(modelo, v.tipo);
    if (valor === '') continue;
    if (!(Number(valor) > 0)) return `El ${porcentaje ? 'porcentaje' : 'monto por unidad'} de ${modelo.label} debe ser mayor que cero.`;
    if (porcentaje && Number(valor) > 100) return `El porcentaje de ${modelo.label} no puede superar 100.`;
  }
  return null;
};

/**
 * Why the shared cap cannot be saved, or null: units must be plain digits above zero, money a plain decimal above
 * zero with up to 2 decimals (the backend's NUMERIC(18, 2) refuses more instead of rounding). Plain notation only:
 * "1e3" is refused here rather than by the backend.
 */
export const errorDeTope = (v) => {
  const unidades = normalizarTope(v.topeUnidades);
  if (unidades !== null && !(/^\d+$/.test(unidades) && Number(unidades) > 0)) return 'El tope de unidades debe ser un número entero mayor que cero.';
  const monto = normalizarTope(v.topeMonto);
  if (monto !== null && !/^\d+(\.\d+)?$/.test(monto)) return 'El tope de monto debe ser un número mayor que cero.';
  if (monto !== null && !(Number(monto) > 0)) return 'El tope de monto debe ser mayor que cero.';
  if (monto !== null && !/^\d+(\.\d{1,2})?$/.test(monto)) return 'El tope de monto admite hasta 2 decimales.';
  return null;
};

/** What is left of the bonus's cap ("20 u de 100 · USD 500,00 de USD 3.000,00"), or null without a cap. */
export const restanteDeTope = (bono, formatEntero, formatMonto) => {
  const partes = [];
  if (bono.tope_unidades != null) partes.push(`${formatEntero(bono.tope_unidades_restantes)} u de ${formatEntero(bono.tope_unidades)}`);
  if (bono.tope_monto != null) partes.push(`${formatMonto(bono.tope_monto_restante, bono.moneda)} de ${formatMonto(bono.tope_monto, bono.moneda)}`);
  return partes.length ? partes.join(' · ') : null;
};

const FALTA_ALCANCE = { marca: 'marca', categoria: 'categoría', modelos: 'al menos un modelo', factura: 'pedido de compra' };

/** What the operator must fill, for the "Faltan datos" message. */
export const faltanDatos = (v) =>
  `Faltan datos: ${FALTA_ALCANCE[v.alcance]}, ${v.tipo === 'porcentaje' ? 'porcentaje' : 'monto por unidad'} y fechas de factura.`;

/** What the bonus reaches, in a few words: "Marca TP-LINK", "Categoría Switches", "2 modelos", "Factura N° P-00042". */
export const alcanceDeBono = (bono) => {
  switch (bono.alcance) {
    case 'categoria':
      return `Categoría ${bono.categoria}`;
    case 'modelos':
      return bono.modelos.length === 1 ? '1 modelo' : `${bono.modelos.length} modelos`;
    case 'factura':
      return bono.pedido_id ? `Factura N° ${bono.pedido_numero ?? bono.pedido_id}` : 'Factura (operación borrada)';
    default:
      return `Marca ${bono.marca}`;
  }
};
