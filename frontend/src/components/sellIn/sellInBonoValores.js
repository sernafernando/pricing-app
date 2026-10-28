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

/** The create/edit body (`SellInBonoIn`): a full replace on edit. */
export const bodyDeBono = (valores) => ({
  alcance: valores.alcance,
  ...CAMPO_DEL_ALCANCE[valores.alcance](valores),
  tipo: valores.tipo,
  ...(valores.tipo === 'porcentaje' ? { porcentaje: valores.porcentaje } : { monto_unit: valores.montoUnit }),
  moneda: valores.moneda,
  fecha_desde: valores.fechaDesde,
  fecha_hasta: valores.fechaHasta,
  descripcion: valores.descripcion.trim() || null,
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
