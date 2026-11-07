/**
 * The lines of the Nuevo tactical screen: their state, what each can charge at most, what stops a save, and the
 * body of `POST /tacticals` (handoffs/tactical-tarea.md, API contract). Pure functions, no React.
 *
 * A line is `{ id, alcance, productos, facturas, marca, categoria, monto, modo, topeUnidades, topeMonto, compartido }`:
 * `productos` are catalog rows (`item_id`, `codigo`, `descripcion`), `facturas` Compras operations (`id` is the
 * pedido_compra_id), `monto`/`topeUnidades`/`topeMonto` the text as typed, `modo` `por_unidad` | `porcentaje` |
 * `monto_total`, and `compartido` whether a line with several products shares one cap.
 */

import { tiendasDelContrato } from './tacticalTiendas';

let siguienteId = 0;

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

/** Several products may share one cap; one product, a brand, a category or an invoice cannot. */
export const puedeCompartir = (linea) => linea.alcance === 'productos' && linea.productos.length > 1;
export const esCompartida = (linea) => puedeCompartir(linea) && linea.compartido;

/** How many times a line's caps count: once per product when each product has its own caps, else once. */
export const vecesDelTope = (linea) =>
  linea.alcance === 'productos' && !esCompartida(linea) ? Math.max(1, linea.productos.length) : 1;

/** The units a line can reach at most (its unit cap, per product when the caps are), or 0 without a unit cap. */
export const unidadesDelTope = (linea) => (enteroDe(linea.topeUnidades) || 0) * vecesDelTope(linea);

/**
 * The most a line can charge, as the design computes it: a total amount is itself; a percentage only its money cap;
 * an amount per unit times its unit cap (per product, times the products), never above the money cap.
 */
export function maximoACobrar(linea) {
  const monto = numeroDe(linea.monto);
  const topeU = enteroDe(linea.topeUnidades);
  const topeM = numeroDe(linea.topeMonto);
  if (linea.modo === 'monto_total') return monto;
  if (linea.modo === 'porcentaje') return topeM;
  if (!monto || !topeU) return topeM;
  const porUnidades = monto * topeU * vecesDelTope(linea);
  return topeM != null ? Math.min(porUnidades, topeM) : porUnidades;
}

/** What all the lines can charge at most together. */
export const maximoTotal = (lineas) => lineas.reduce((total, linea) => total + (maximoACobrar(linea) || 0), 0);

/** The scope and amount kinds a type offers: invoices and total amounts are sell in only. */
export const alcancesDe = (tipo) =>
  tipo === 'sell_in' ? ['productos', 'marca', 'categoria', 'factura'] : ['productos', 'marca', 'categoria'];
export const modosDe = (tipo) =>
  tipo === 'sell_in' ? ['por_unidad', 'porcentaje', 'monto_total'] : ['por_unidad', 'porcentaje'];

/**
 * The amount kinds a line shows but cannot use: on sell in a total amount is an invoice's only (Contrato final: a
 * cost reduction over products, a brand or a category takes no `monto_total`).
 */
export const modosNoDisponibles = (tipo, alcance) => (tipo === 'sell_in' && alcance !== 'factura' ? ['monto_total'] : []);

/** A line moved to another scope, as the design does: an invoice is charged as a total amount, nothing else is. */
export function conAlcance(linea, alcance) {
  let { modo } = linea;
  if (alcance === 'factura') modo = 'monto_total';
  else if (modo === 'monto_total') modo = 'por_unidad';
  return { ...linea, alcance, modo };
}

/** The lines a type keeps when the user switches to it: sell out has no invoices nor total amounts. */
export function lineasPara(tipo, lineas) {
  if (tipo === 'sell_in') return lineas;
  return lineas.map((linea) => {
    if (linea.alcance === 'factura') return { ...conAlcance(linea, 'productos'), facturas: [] };
    return linea.modo === 'monto_total' ? { ...linea, modo: 'por_unidad' } : linea;
  });
}

const cuantas = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

/** What stops a save, the first thing only, in the design's words; null when it can be sent. */
export function problemaDe(form, lineas) {
  if (!form.nombre.trim()) return 'Poné un nombre para el tactical antes de crearlo.';
  if (!form.marca) return 'Elegí la marca del tactical.';
  if (!form.fechaDesde || !form.fechaHasta) return 'Completá la vigencia del tactical.';
  if (form.fechaDesde > form.fechaHasta) return 'La fecha desde no puede ser posterior a la fecha hasta.';
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
    mal((l) => l.modo === 'porcentaje' && numeroDe(l.monto) > 100, 'un porcentaje mayor a 100', '') ||
    mal((l) => ilegible(l.topeUnidades) || ilegible(l.topeMonto), 'un tope que no es un número', ' o borrá el tope') ||
    mal((l) => numeroDe(l.topeUnidades) != null && !Number.isInteger(numeroDe(l.topeUnidades)), 'un tope de unidades que no es entero', '') ||
    null
  );
}

/** One line of the contract; an invoice line becomes one per chosen invoice. */
function lineasDelContrato(linea) {
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
  if (linea.alcance === 'marca') return [{ alcance: 'marca', marca: linea.marca, ...comun }];
  if (linea.alcance === 'categoria') return [{ alcance: 'categoria', categoria: linea.categoria, ...comun }];
  return linea.facturas.map((f) => ({ alcance: 'factura', pedido_compra_id: f.id, ...comun }));
}

/**
 * `{ body, origen }`: the body of `POST /tacticals`, and for each of its lines the screen line it came from
 * (`origen[i]` is the 1-based screen line of the body's line i + 1), so a message naming a body line can name the
 * line the user sees.
 */
export function cuerpoDe(form, lineas, gruposTiendas = []) {
  const usd = form.moneda === 'USD';
  const body = {
    tipo: form.tipo,
    nombre: form.nombre.trim(),
    marca: form.marca,
    referencia: form.referencia.trim() || null,
    fecha_desde: form.fechaDesde,
    fecha_hasta: form.fechaHasta,
    moneda: form.moneda,
    // ARS sends neither exchange-rate field; `tipo_cambio` goes only with a fixed rate (Contrato final).
    ...(usd ? { tc_modo: form.tcModo } : {}),
    ...(usd && form.tcModo === 'fijo' ? { tipo_cambio: numeroDe(form.tipoCambio) } : {}),
    incluye_iva: form.incluyeIva,
    acumulable: form.acumulable,
    todas_tiendas: form.todasTiendas !== false,
    tope_compartido: Boolean(form.topeCompartido),
    tiendas: tiendasDelContrato(form.todasTiendas !== false, form.tiendaKeys ?? [], gruposTiendas),
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
