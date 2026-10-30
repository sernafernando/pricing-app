/**
 * The split of a `monto_total` campaign (T26c/T26d, S34/S35) as the reparto section holds it: one row per product,
 * its share a % of the total or a fixed amount. The live totals and the guard mirror `reparto.validar` (a fixed share
 * has the total's sign, |Σ| <= |total| on the exact shares, before any rounding) so the PM sees them before saving;
 * the API stays the source of
 * truth and its 422/403 message is what the panel shows when it refuses.
 */
import { formatMonto } from '../sellIn/sellInFormat';

const MILES = new Intl.NumberFormat('es-AR');
import { nombreDeItem } from './sellOutFormat';

export const MODO_PORCENTAJE = 'porcentaje';
export const MODO_MONTO = 'monto';

const texto = (value) => (value === null || value === undefined ? '' : String(value));
const numero = (value) => (String(value ?? '').trim() === '' ? NaN : Number(value));

// Exact math in micro-cents (1e-6 of a cent): a 4-decimal % of a cents total is a whole number of them, so the sum is
// compared before rounding, like the backend's Decimal (`reparto.validar`); only what is shown is rounded to cents.
const MICRO = 1000000n;

/** `value` (a typed decimal) times 10^decimales as a BigInt, half away from zero beyond those decimals; null if unset. */
function escalar(value, decimales) {
  const limpio = String(value ?? '').trim();
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(limpio);
  if (!match || (match[2] === '' && !match[3])) return null;
  const [, signo, entero, fraccion = ''] = match;
  const digitos = BigInt(`${entero || '0'}${fraccion.slice(0, decimales).padEnd(decimales, '0')}`);
  const redondeo = Number(fraccion[decimales] ?? 0) >= 5 ? 1n : 0n;
  return signo === '-' ? -(digitos + redondeo) : digitos + redondeo;
}

/** Micro-cents to cents, half away from zero. */
function aCentavosDesdeMicro(micro) {
  const negativo = micro < 0n;
  const abs = negativo ? -micro : micro;
  const cents = (abs + MICRO / 2n) / MICRO;
  return Number(negativo ? -cents : cents);
}

/** An amount in cents, half away from zero: the one rounding rule of rows, totals and the guard. */
export const aCentavos = (value) => {
  const cents = escalar(value, 2);
  return cents === null ? NaN : Number(cents);
};

/** A row's exact share in micro-cents (a % share is a % of the total, sign kept); null when unset. */
function microDeFila(totalCentavos, fila) {
  const valor = escalar(fila.valor, fila.modo === MODO_PORCENTAJE ? 4 : 2);
  if (valor === null) return null;
  return fila.modo === MODO_PORCENTAJE ? BigInt(totalCentavos) * valor : valor * MICRO;
}

/**
 * An exact amount in micro-cents like the backend's `_importe`: two decimals when it is whole cents, else every
 * decimal it has (so an excess below a cent never reads 0,00): "$ 100,00", "$ 0,0001".
 */
function formatMicro(micro, moneda) {
  if (micro % MICRO === 0n) return formatMonto(Number(micro / MICRO) / 100, moneda);
  const negativo = micro < 0n;
  const abs = negativo ? -micro : micro;
  const unidad = 100n * MICRO; // micro-cents per currency unit
  const entero = MILES.format(abs / unidad);
  const decimales = String(abs % unidad).padStart(8, '0').replace(/0+$/, '');
  return `${moneda === 'USD' ? 'USD' : '$'} ${negativo ? '-' : ''}${entero},${decimales}`;
}

const sumaMicro = (totalCentavos, filas) => filas.reduce((acc, fila) => acc + (microDeFila(totalCentavos, fila) ?? 0n), 0n);

/** A stored campaign's shares as rows: `{ itemId, codigo, descripcion, modo, valor }`. */
export function filasDeCampana(campana) {
  return (campana.items ?? []).map((i) => ({
    itemId: i.item_id,
    codigo: i.codigo ?? null,
    descripcion: i.descripcion ?? null,
    modo: i.reparto_monto != null ? MODO_MONTO : MODO_PORCENTAJE,
    valor: texto(i.reparto_monto ?? i.reparto_porcentaje),
  }));
}

/** A row's share in cents of the campaign currency (a % share is a % of the total, sign kept); null when unset. */
export function centavosDeFila(totalCentavos, fila) {
  const micro = microDeFila(totalCentavos, fila);
  return micro === null ? null : aCentavosDesdeMicro(micro);
}

/**
 * The cents assigned to shares this user does not hold: a brand-scoped PM gets only their brands' shares, while the
 * server keeps the others (T26c). The server's `resumen.reparto.asignado` minus the stored shares listed here; 0 when
 * the server could not compute it (`motivo`).
 */
export function centavosAjenos(campana) {
  const asignado = campana.resumen?.reparto?.asignado;
  if (asignado === null || asignado === undefined) return 0;
  // The server sums each share already rounded to cents (`reparto._cargada`), so the visible ones are summed the
  // same way: with every share visible the difference is exactly 0, whatever the rounding of each.
  const totalCentavos = aCentavos(campana.monto_total);
  const propios = filasDeCampana(campana).reduce((acc, fila) => acc + (centavosDeFila(totalCentavos, fila) ?? 0), 0);
  return aCentavos(asignado) - propios;
}

/**
 * What the rows assign, plus `ajenos` (cents of shares the user cannot see, see `centavosAjenos`), and what stays
 * unassigned (total − Σ, same sign as the total), in the campaign currency.
 */
export function totalesDeReparto(total, filas, ajenos = 0) {
  const totalCentavos = aCentavos(total);
  const asignado = aCentavosDesdeMicro(sumaMicro(totalCentavos, filas) + BigInt(ajenos) * MICRO);
  return { asignado: asignado / 100, sinAsignar: (totalCentavos - asignado) / 100 };
}

/** Why the API would refuse the rows, in its words (products named by code); null when they can be sent. */
export function errorDeReparto(total, filas, moneda, ajenos = 0) {
  const totalCentavos = aCentavos(total);
  for (const fila of filas) {
    const valor = numero(fila.valor);
    if (!Number.isFinite(valor) || valor === 0) {
      return `El producto ${nombreDeItem(fila)} necesita un porcentaje o un monto de reparto`;
    }
    if (fila.modo === MODO_PORCENTAJE && !(valor > 0 && valor <= 100)) {
      return 'El porcentaje de reparto tiene que ser mayor a 0 y hasta 100';
    }
    if (fila.modo === MODO_MONTO && Math.sign(valor) !== Math.sign(totalCentavos)) {
      return `El reparto del producto ${nombreDeItem(fila)} tiene que tener el signo del monto total`;
    }
  }
  const suma = sumaMicro(totalCentavos, filas) + BigInt(ajenos) * MICRO;
  const absoluto = (n) => (n < 0n ? -n : n);
  if (absoluto(suma) > absoluto(BigInt(totalCentavos) * MICRO)) {
    // Like the API's message (`_importe`): the exact sum, the total and the excess between them.
    const totalMicro = BigInt(totalCentavos) * MICRO;
    const exceso = absoluto(suma) - absoluto(totalMicro);
    return `El reparto (${formatMicro(suma, moneda)}) supera el monto total (${formatMicro(totalMicro, moneda)}) en ${formatMicro(exceso, moneda)}`;
  }
  return null;
}

/** `PUT /reparto`'s `repartos`: each row with exactly one of its share fields, as typed (the API reads Decimal). */
export function repartosDeFilas(filas) {
  return filas.map((fila) => ({
    item_id: fila.itemId,
    [fila.modo === MODO_MONTO ? 'reparto_monto' : 'reparto_porcentaje']: String(fila.valor).trim(),
  }));
}
