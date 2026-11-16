/**
 * The lines of the Nuevo tactical screen: their state, what each can charge at most, what stops a save, and the
 * body of `POST /tacticals` (handoffs/tactical-tarea.md, API contract). Pure functions, no React.
 *
 * A line is `{ id, alcance, productos, facturas, marca, categoria, monto, modo, topeUnidades, topeMonto, compartido,
 * reparto }`:
 * `productos` are catalog rows (`item_id`, `codigo`, `descripcion`), `facturas` Compras operations (`id` is the
 * pedido_compra_id; their own `facturas` are the invoices linked to it, and `facturasCt` the CT ids of the ones the
 * line is limited to, or null for all of them), `monto`/`topeUnidades`/`topeMonto` the text as typed, `modo` `por_unidad` | `porcentaje` |
 * `monto_total`, `compartido` whether a line with several products shares one cap, and `reparto` how a sell out total
 * amount is split among the line's products (`REPARTOS`, '' until chosen).
 */

import { ALCANCE_POR_TIENDA, tiendasDelContrato } from './tacticalTiendas';

let siguienteId = 0;

/**
 * How a sell out total amount is split among the products of its line, as `reparto_criterio` (S1): equal parts, by
 * the units sold in the tactical's dates (it follows sales and returns), or by each product's cost.
 */
export const REPARTOS = [
  { value: 'iguales', label: 'Partes iguales por modelo' },
  { value: 'unidades', label: 'Según unidades vendidas' },
  { value: 'costo', label: 'Proporcional al costo' },
];

/** A total amount split among the line's products: any scope but an invoice (whose split is what was invoiced). */
export const repartePorCriterio = (linea) => linea.modo === 'monto_total' && linea.alcance !== 'factura';

/** An amount as the design writes it: "$ 850.000" in pesos, "USD 19.800" in dollars, rounded to units. */
export const dinero = (moneda, n) => `${moneda === 'ARS' ? '$' : 'USD'} ${Math.round(n).toLocaleString('es-AR')}`;

export const nuevaLinea = (marca = '') => ({
  id: ++siguienteId,
  alcance: 'productos',
  productos: [],
  facturas: [],
  marca,
  categoria: '',
  monto: '',
  modo: 'por_unidad',
  topeUnidades: '',
  topeMonto: '',
  compartido: false,
  reparto: '',
});

export const copiarLinea = (linea) => ({
  ...linea,
  id: ++siguienteId,
  productos: [...linea.productos],
  facturas: [...linea.facturas],
});

/** An es-AR amount as typed ("3,6", "1.500", "850000") -> its number, or null when empty or not a number. */
export function numeroDe(texto) {
  const limpio = String(texto ?? '').trim().replace(/\s/g, '').replace(/\./g, '').replace(',', '.');
  if (limpio === '') return null;
  const n = Number(limpio);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** A whole number as typed, or null. */
const enteroDe = (texto) => {
  const n = numeroDe(texto);
  return n == null ? null : Math.floor(n);
};

/**
 * An operation's invoice pick after checking or unchecking one invoice (varias facturas S3): from all invoices
 * (`null`) to that one, and back to all when the last one is unchecked, so an empty pick never goes out.
 */
export function alternarFactura(facturasCt, ct) {
  if (!facturasCt?.length) return [ct];
  const resto = facturasCt.filter((c) => c !== ct);
  if (resto.length === facturasCt.length) return [...facturasCt, ct];
  return resto.length ? resto : null;
}

/** Several products may share one cap; one product, a brand, a category or an invoice cannot. */
export const puedeCompartir = (linea) => linea.alcance === 'productos' && linea.productos.length > 1;
export const esCompartida = (linea) => puedeCompartir(linea) && linea.compartido;

/** How many times a line's caps count: once per product when each product has its own caps, else once. */
export const vecesDelTope = (linea) =>
  linea.alcance === 'productos' && !esCompartida(linea) ? Math.max(1, linea.productos.length) : 1;

/**
 * The units a line can reach at most (its unit cap, per product when the caps are), or 0 without a unit cap; a total
 * amount split by criterion has none.
 */
export const unidadesDelTope = (linea) =>
  repartePorCriterio(linea) ? 0 : (enteroDe(linea.topeUnidades) || 0) * vecesDelTope(linea);

/**
 * The most a line can charge, as the design computes it: a total amount is itself; a percentage only its money cap;
 * an amount per unit times its unit cap (per product, times the products), never above the money cap.
 */
export function maximoACobrar(linea, contadores = 1) {
  const monto = numeroDe(linea.monto);
  const topeU = enteroDe(linea.topeUnidades);
  const topeM = numeroDe(linea.topeMonto);
  if (linea.modo === 'monto_total') return monto; // a total is split once, never per store
  const porContador = (valor) => (valor == null ? valor : valor * contadores);
  if (linea.modo === 'porcentaje') return porContador(topeM);
  if (!monto || !topeU) return porContador(topeM);
  const porUnidades = monto * topeU * vecesDelTope(linea);
  return porContador(topeM != null ? Math.min(porUnidades, topeM) : porUnidades);
}

/** What all the lines can charge at most together; `contadores` caps per line (`contadoresDelTope`). */
export const maximoTotal = (lineas, contadores = 1) =>
  lineas.reduce((total, linea) => total + (maximoACobrar(linea, contadores) || 0), 0);

/** The scope and amount kinds a type offers: invoices are sell in only; both offer a total amount on every scope. */
export const alcancesDe = (tipo) =>
  tipo === 'sell_in' ? ['productos', 'marca', 'categoria', 'factura'] : ['productos', 'marca', 'categoria'];
export const modosDe = () => ['por_unidad', 'porcentaje', 'monto_total'];

/**
 * Whether a sell in total amount over products, a brand or a category cannot go in this currency: the backend takes
 * it in ARS, or in USD converted at the tactical's fixed rate (S4). The invoice total line keeps its own rules.
 */
const totalSinTipoDeCambio = (tipo, alcance, moneda, tcModo) =>
  tipo === 'sell_in' && alcance !== 'factura' && moneda === 'USD' && tcModo !== 'fijo';

/** Why a sell in total amount in USD is off, in the backend's words. */
export const TOTAL_USD_SIN_TC_FIJO = 'Un monto total en USD necesita tipo de cambio fijo.';

/** The amount kinds a line shows but cannot use: a sell in total amount in USD without a fixed rate (S4). */
export const modosNoDisponibles = (tipo, alcance, moneda, tcModo) =>
  totalSinTipoDeCambio(tipo, alcance, moneda, tcModo) ? ['monto_total'] : [];

/**
 * A line with another amount kind: a total amount split by criterion takes no caps (S1), so they are cleared, and
 * the criterion goes when it stops being one.
 */
export function conModo(linea, modo) {
  const cambiada = { ...linea, modo };
  if (repartePorCriterio(cambiada)) return { ...cambiada, topeUnidades: '', topeMonto: '', compartido: false };
  return { ...cambiada, reparto: '' };
}

/**
 * A line moved to another scope, as the design does: an invoice is charged as a total amount, and leaving it goes
 * back to per unit; a sell out total amount keeps its kind across products, brand and category.
 */
export function conAlcance(linea, alcance) {
  let { modo } = linea;
  // A brand line's category narrows that brand (SISO S3): it means something else on any other scope.
  if ((alcance === 'marca') !== (linea.alcance === 'marca')) linea = { ...linea, categoria: '' };
  if (alcance === 'factura') modo = 'monto_total';
  else if (linea.alcance === 'factura') modo = 'por_unidad';
  return conModo({ ...linea, alcance }, modo);
}

/**
 * The lines a type keeps when the user switches to it: sell out has no invoices; sell in keeps every line (a total
 * amount split by criterion included, S4).
 */
export function lineasPara(tipo, lineas) {
  return lineas.map((linea) => {
    if (tipo === 'sell_in') return linea;
    return linea.alcance === 'factura' ? { ...conAlcance(linea, 'productos'), facturas: [] } : linea;
  });
}

const cuantas = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

/**
 * Every line of a sell in tactical is an invoice line (factura sin fecha S2c): it has no dates, each invoice applies
 * until its units are sold, and the server fills the header from the invoices.
 */
export const porFactura = (form, lineas) =>
  form.tipo === 'sell_in' && lineas.length > 0 && lineas.every((l) => l.alcance === 'factura');

/** What stops a save, the first thing only, in the design's words; null when it can be sent. */
export function problemaDe(form, lineas) {
  if (!form.nombre.trim()) return 'Poné un nombre para el tactical antes de crearlo.';
  if (!form.marcas?.length) return 'Elegí la marca del tactical.';
  if (!porFactura(form, lineas)) {
    if (!form.fechaDesde || !form.fechaHasta) return 'Completá la vigencia del tactical.';
    if (form.fechaDesde > form.fechaHasta) return 'La fecha desde no puede ser posterior a la fecha hasta.';
  }
  if (form.moneda === 'USD' && form.tcModo === 'fijo' && !(numeroDe(form.tipoCambio) > 0)) {
    return 'Completá el tipo de cambio fijo.';
  }
  if (!lineas.length) return 'Agregá al menos una línea antes de crear el tactical.';
  const faltan = (falta, que) => {
    const n = lineas.filter(falta).length;
    return n ? `Hay ${cuantas(n, 'línea', 'líneas')} sin ${que}. ${n === 1 ? 'Completala o eliminala' : 'Completalas o eliminalas'}.` : null;
  };
  // A cap exists to bound the money: one typed but unreadable must stop the save, never go out as "no cap".
  const mal = (falla, que, arreglo) => {
    const n = lineas.filter(falla).length;
    return n ? `Hay ${cuantas(n, 'línea', 'líneas')} con ${que}. ${n === 1 ? 'Corregila' : 'Corregilas'}${arreglo}.` : null;
  };
  const ilegible = (texto) => String(texto ?? '').trim() !== '' && numeroDe(texto) == null;
  return (
    faltan((l) => l.alcance === 'productos' && !l.productos.length, 'productos') ||
    faltan((l) => l.alcance === 'factura' && !l.facturas.length, 'factura') ||
    faltan((l) => l.alcance === 'marca' && !l.marca, 'marca') ||
    faltan((l) => l.alcance === 'categoria' && !l.categoria, 'categoría') ||
    faltan((l) => !(numeroDe(l.monto) > 0), 'monto') ||
    faltan((l) => repartePorCriterio(l) && !l.reparto, 'reparto del monto total') ||
    mal(
      (l) => repartePorCriterio(l) && totalSinTipoDeCambio(form.tipo, l.alcance, form.moneda, form.tcModo),
      'un monto total en USD sin tipo de cambio fijo',
      ' o elegí tipo de cambio fijo',
    ) ||
    mal((l) => l.modo === 'porcentaje' && numeroDe(l.monto) > 100, 'un porcentaje mayor a 100', '') ||
    mal((l) => ilegible(l.topeUnidades) || ilegible(l.topeMonto), 'un tope que no es un número', ' o borrá el tope') ||
    mal((l) => numeroDe(l.topeUnidades) != null && !Number.isInteger(numeroDe(l.topeUnidades)), 'un tope de unidades que no es entero', '') ||
    null
  );
}

/** A brand line's scope: its brand, and the category it narrows to when one is chosen (SISO S3). */
const deMarca = (linea) => ({
  alcance: 'marca',
  marca: linea.marca,
  ...(linea.categoria ? { categoria: linea.categoria } : {}),
});

/** One line of the contract; an invoice line becomes one per chosen invoice. */
function lineasDelContrato(linea) {
  // A total amount split by criterion has no caps (S1): it sends its criterion instead, and no tope_por_producto.
  if (repartePorCriterio(linea)) {
    const total = { modo_monto: 'monto_total', valor: numeroDe(linea.monto), tope_unidades: null, tope_monto: null };
    const criterio = { reparto_criterio: linea.reparto };
    if (linea.alcance === 'productos') {
      return [{ alcance: 'productos', item_ids: linea.productos.map((p) => p.item_id), ...total, ...criterio }];
    }
    if (linea.alcance === 'marca') return [{ ...deMarca(linea), ...total, ...criterio }];
    return [{ alcance: 'categoria', categoria: linea.categoria, ...total, ...criterio }];
  }
  const comun = {
    modo_monto: linea.modo,
    valor: numeroDe(linea.monto),
    tope_unidades: enteroDe(linea.topeUnidades),
    tope_monto: numeroDe(linea.topeMonto),
  };
  // `tope_por_producto` goes on products lines only (Contrato final); one invoice per contract line.
  if (linea.alcance === 'productos') {
    const item_ids = linea.productos.map((p) => p.item_id);
    return [{ alcance: 'productos', item_ids, ...comun, tope_por_producto: !esCompartida(linea) }];
  }
  if (linea.alcance === 'marca') return [{ ...deMarca(linea), ...comun }];
  if (linea.alcance === 'categoria') return [{ alcance: 'categoria', categoria: linea.categoria, ...comun }];
  // No `facturas_ct` is every invoice of the operation, also those linked later; a pick sends its CT ids.
  return linea.facturas.map((f) => ({
    alcance: 'factura',
    pedido_compra_id: f.id,
    ...(f.facturasCt?.length ? { facturas_ct: [...f.facturasCt] } : {}),
    ...comun,
  }));
}

/**
 * `{ body, origen }`: the body of `POST /tacticals`, and for each of its lines the screen line it came from
 * (`origen[i]` is the 1-based screen line of the body's line i + 1), so a message naming a body line can name the
 * line the user sees.
 */
export function cuerpoDe(form, lineas, gruposTiendas = [], alcancePorTienda = ALCANCE_POR_TIENDA) {
  const usd = form.moneda === 'USD';
  const body = {
    tipo: form.tipo,
    nombre: form.nombre.trim(),
    marcas: form.marcas,
    referencia: form.referencia.trim() || null,
    // An all-invoice tactical has no dates: the server takes them from its invoices.
    fecha_desde: porFactura(form, lineas) ? null : form.fechaDesde,
    fecha_hasta: porFactura(form, lineas) ? null : form.fechaHasta,
    moneda: form.moneda,
    // ARS sends neither exchange-rate field; `tipo_cambio` goes only with a fixed rate (Contrato final).
    ...(usd ? { tc_modo: form.tcModo } : {}),
    ...(usd && form.tcModo === 'fijo' ? { tipo_cambio: numeroDe(form.tipoCambio) } : {}),
    incluye_iva: form.incluyeIva,
    acumulable: form.acumulable,
    ...(alcancePorTienda
      ? {
          todas_tiendas: form.todasTiendas !== false,
          tope_compartido: Boolean(form.topeCompartido),
          tiendas: tiendasDelContrato(form.todasTiendas !== false, form.tiendaKeys ?? [], gruposTiendas),
        }
      : {}),
    nota: form.nota.trim() || null,
    lineas: [],
  };
  const origen = [];
  lineas.forEach((linea, index) => {
    lineasDelContrato(linea).forEach((l) => {
      body.lineas.push(l);
      origen.push(index + 1);
    });
  });
  return { body, origen };
}

/** "Línea 3: …" of the body -> "Línea N: …" of the screen; any other message stays as it is. */
export function conLineaDeLaPantalla(mensaje, origen) {
  return mensaje.replace(/^Línea (\d+):/, (todo, n) => (origen[Number(n) - 1] ? `Línea ${origen[Number(n) - 1]}:` : todo));
}
