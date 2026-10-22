import { formatMonto } from '../sellIn/sellInFormat';

const PORCENTAJE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 4 });

export const TC_MODO_LABELS = { al_cobro: 'Al cobro', fijo: 'Fijo', dia_venta: 'Del día de la venta' };
export const CANAL_LABELS = { ml: 'Mercado Libre', fuera: 'Fuera de ML', tn: 'Tienda Nube' };
const BASE_LABELS = { costo: 'del costo', precio_neto: 'del precio neto' };
const RECALCULO_LABELS = { al_dia: 'Al día', en_cola: 'En cola', recalculando: 'Recalculando', fallida: 'Falló' };

/** What a campaign credits per sale: "USD 36,00 por unidad" or "2% del precio neto". */
export function beneficio(campana) {
  if (campana.tipo === 'porcentaje') {
    return `${PORCENTAJE.format(Number(campana.porcentaje))}% ${BASE_LABELS[campana.base_porcentaje] ?? ''}`.trim();
  }
  return `${formatMonto(campana.monto_unit, campana.moneda)} por unidad`;
}

/** The recalculation state, with its error when it failed. */
export function recalculo(estado) {
  if (!estado) return '—';
  const label = RECALCULO_LABELS[estado.estado] ?? estado.estado;
  return estado.estado === 'fallida' && estado.error ? `${label}: ${estado.error}` : label;
}
