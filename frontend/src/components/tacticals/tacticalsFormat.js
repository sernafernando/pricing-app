import { formatDateOnly, parseDateOnly } from '../../utils/dateUtils';

/** Display and request helpers of the tactical list (`GET /tacticals`). */

const NUMERO = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });
const PORCENTAJE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 4 });
const DIA_MES_ANIO = { day: '2-digit', month: '2-digit', year: 'numeric' };
/** "Vence en N días" shows from this many days before the end (handoffs/tactical-tarea.md, decision T5). */
const DIAS_AVISO = 7;
/** Past this share of its cap a bar turns to warning. */
const AVISO_PORCENTAJE = 90;
const MS_DIA = 24 * 60 * 60 * 1000;

/** No value: null, undefined or an empty string (decimals come as strings). */
export const vacio = (value) => value === null || value === undefined || value === '';
const redondear = (n) => Math.round(n * 10) / 10;

/** `USD 3.000`, `ARS 1.240.000`: the tactical's currency code, es-AR thousands, no forced decimals. */
export function formatMontoTactical(value, moneda) {
  if (vacio(value)) return '—';
  const num = Number(value);
  return Number.isNaN(num) ? '—' : `${moneda} ${NUMERO.format(num)}`;
}

export const formatUnidades = (value) => (vacio(value) ? '—' : NUMERO.format(Number(value)));

/** The line's amount as it was loaded, in the line's own currency: `USD 220 / u`, `3,5 %` or `USD 3.000`;
 * a sell in total loaded in USD: `USD 1.200,01 → ARS 1.200.610,01 (TC 1.000,5)`. */
export function valorDeLinea({ modo_monto: modo, valor, moneda, valor_usd: valorUsd }, tipoCambio) {
  if (modo === 'porcentaje') return `${PORCENTAJE.format(Number(valor))} %`;
  const monto = formatMontoTactical(valor, moneda);
  // A sell in total loaded in USD: its bonus keeps the ARS total at the tactical's fixed rate; both are shown.
  if (!vacio(valorUsd)) {
    const tc = vacio(tipoCambio) ? '' : ` (TC ${PORCENTAJE.format(Number(tipoCambio))})`;
    return `${formatMontoTactical(valorUsd, 'USD')} → ${monto}${tc}`;
  }
  return modo === 'por_unidad' ? `${monto} / u` : monto;
}

/**
 * `01/11 al 30/11/2026`. The start is cut from the full date: es-AR does not pad a day-month-only format. An
 * all-invoice tactical (`por_factura`) has no range: each invoice applies until its units are sold.
 */
export const vigenciaDe = (desde, hasta, porFactura = false) =>
  porFactura ? 'Por factura' : `${formatDateOnly(desde, DIA_MES_ANIO).slice(0, 5)} al ${formatDateOnly(hasta, DIA_MES_ANIO)}`;

/**
 * The state pill: Anulado, Esperando factura (an invoice line saved before Compras linked its invoice: it applies
 * nothing until then), Vencido, Vence hoy / en N días, or Vigente (an all-invoice tactical never ends).
 */
export function estadoDe(
  { estado, fecha_hasta: hasta, por_factura: porFactura, esperando_factura: esperandoFactura },
  hoy = new Date(),
) {
  if (estado === 'anulado') return { texto: 'Anulado', tono: 'neutral' };
  if (esperandoFactura) return { texto: 'Esperando factura', tono: 'warning' };
  if (porFactura) return { texto: 'Vigente', tono: 'success' };
  const fin = parseDateOnly(hasta);
  const dia = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
  const restan = fin ? Math.round((fin - dia) / MS_DIA) : null;
  if (restan === null || restan > DIAS_AVISO) return { texto: 'Vigente', tono: 'success' };
  if (restan < 0) return { texto: 'Vencido', tono: 'neutral' };
  if (restan === 0) return { texto: 'Vence hoy', tono: 'warning' };
  return { texto: `Vence en ${restan} ${restan === 1 ? 'día' : 'días'}`, tono: 'warning' };
}

/** An invoice of a Compras operation by its ERP number, or by its CT id when the mirror has no number. */
export const etiquetaFactura = (f) => f.numero || `CT ${f.ct_transaction_id}`;

/**
 * Which invoices of its operation an invoice line covers (varias facturas S5): every one, also those linked later
 * (`null`), or the ones picked, by number.
 */
export const facturasCubiertas = (elegidas) =>
  elegidas?.length ? elegidas.map(etiquetaFactura).join(', ') : 'Todas las facturas';

const ESPERANDO_FACTURA = 'Esperando factura: se aplica cuando Compras vincule la factura del proveedor';

/** What a brand, category or invoice line reaches; product lines are shown as chips instead. */
export function alcanceDe(linea) {
  if (linea.alcance === 'marca' && linea.categoria) {
    return { titulo: `Marca ${linea.marca} · ${linea.categoria}`, detalle: 'Los productos de la marca en esa categoría' };
  }
  if (linea.alcance === 'marca') return { titulo: `Marca ${linea.marca}`, detalle: 'Todos los productos de la marca' };
  if (linea.alcance === 'categoria') {
    return { titulo: `Categoría ${linea.categoria}`, detalle: 'Todos los productos de la categoría' };
  }
  return {
    titulo: `Factura del pedido ${linea.pedido_numero ?? `#${linea.pedido_compra_id}`} · ${facturasCubiertas(linea.facturas_elegidas)}`,
    detalle: linea.esperando_factura ? ESPERANDO_FACTURA : null,
  };
}

function medir(usado, tope) {
  if (!(tope > 0)) return null;
  // Full only when the cap is really reached: 2499 of 2500 rounds to 100 but still has room, so it stays below it.
  const lleno = usado >= tope;
  const porcentaje = lleno ? 100 : Math.min(99.9, redondear((usado / tope) * 100));
  const tono = lleno ? 'full' : porcentaje > AVISO_PORCENTAJE ? 'warn' : 'normal';
  return { porcentaje, tono };
}

/** How much of its cap a line used: the unit cap when it has one, else the money cap, else nothing to measure. */
export function avanceDeLinea(linea) {
  if (!vacio(linea.tope_unidades)) return medir(Number(linea.unidades_usadas ?? 0), Number(linea.tope_unidades));
  if (!vacio(linea.tope_monto)) return medir(Number(linea.monto_usado ?? 0), Number(linea.tope_monto));
  return null;
}

/**
 * The header row's progress (decision T5): units used over the unit caps of the lines that have one, and the money
 * used per currency (a USD tactical's cost-reduction lines count in ARS), with the money cap of a currency only when
 * every line in it has one: `USD 300 · ARS 12.000 de ARS 50.000`.
 */
export function avanceDeTactical(lineas) {
  const conTope = lineas.filter((l) => !vacio(l.tope_unidades));
  let unidades = null;
  if (conTope.length > 0) {
    const usadas = conTope.reduce((s, l) => s + Number(l.unidades_usadas ?? 0), 0);
    const tope = conTope.reduce((s, l) => s + Number(l.tope_unidades), 0);
    const avance = medir(usadas, tope);
    if (avance) unidades = { usadas, tope, ...avance };
  }
  const monedas = [...new Set(lineas.map((l) => l.moneda))];
  const monto = monedas
    .map((moneda) => {
      const deMoneda = lineas.filter((l) => l.moneda === moneda);
      const usado = formatMontoTactical(deMoneda.reduce((s, l) => s + Number(l.monto_usado ?? 0), 0), moneda);
      if (!deMoneda.every((l) => !vacio(l.tope_monto))) return usado;
      return `${usado} de ${formatMontoTactical(deMoneda.reduce((s, l) => s + Number(l.tope_monto), 0), moneda)}`;
    })
    .join(' · ');
  return { unidades, monto };
}

/** Columns of a tactical row: the toggle, Nombre, Tipo, Marca, Vigencia, Líneas, Avance, Estado, Cobranza and the
 * actions. */
export const COLUMNAS_TACTICAL = 10;

export const FILTROS_VACIOS = {
  tipo: 'todos',
  marca: '',
  moneda: '',
  estado: 'vigentes',
  cobranza: 'todos',
  desde: '',
  hasta: '',
  q: '',
  contiene: '',
  producto: '',
};

/**
 * A KPI amount (`kpis.*.montos` of the list, tactical cobranza S4): what the lines generated per currency, "of" the
 * lines' money caps when that currency has any (S6): `ARS 4.380.250 de 6.000.000 · USD 1.920`; a dash when none.
 * When only some lines of the currency have a cap (`tope_parcial`), "de" would compare every line's amount with only
 * some lines' cap (`900 de 500`), so the cap reads apart: `ARS 900 · tope 500 (líneas con tope)`.
 */
export const formatMontosKpi = (montos) =>
  montos?.length
    ? montos
        .map(({ moneda, monto, tope, tope_parcial: parcial }) => {
          const generado = formatMontoTactical(monto, moneda);
          if (vacio(tope)) return generado;
          const cifra = NUMERO.format(Number(tope));
          return parcial ? `${generado} · tope ${cifra} (líneas con tope)` : `${generado} de ${cifra}`;
        })
        .join(' · ')
    : '—';

/** The list's query: only the filters that are set ("Todos" sends no tipo nor cobranza). */
export function paramsDeFiltros(filtros, { page, pageSize }) {
  const params = {};
  if (filtros.tipo !== 'todos') params.tipo = filtros.tipo;
  if (filtros.cobranza && filtros.cobranza !== 'todos') params.cobranza = filtros.cobranza;
  for (const campo of ['marca', 'moneda', 'estado', 'desde', 'hasta']) if (filtros[campo]) params[campo] = filtros[campo];
  const q = filtros.q.trim();
  if (q) params.q = q;
  if (filtros.contiene) params.contiene = filtros.contiene;
  const producto = (filtros.producto ?? '').trim();
  if (producto) params.producto = producto;
  return { ...params, page, page_size: pageSize };
}
