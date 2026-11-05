import { numeroDe } from '../tactical/tacticalLineas';
import { alcanceDe, vacio } from './tacticalsFormat';

/**
 * The Editar dialog (tacticals F1): only the name, the note, the end date and each POSTed line's caps change; lines,
 * values and scope do not (that is Anular + Renovar). The detail has one entry per child, grouped back by `linea`.
 */

const texto = (v) => (vacio(v) ? '' : String(Number(v)).replace('.', ','));

function tituloDe(hijos) {
  const [primero] = hijos;
  if (primero.alcance !== 'productos') return alcanceDe(primero).titulo;
  const productos = hijos.reduce((n, h) => n + (h.productos ?? []).length, 0);
  const nombre = productos === 1 ? '1 producto' : `${productos} productos`;
  if (hijos.length > 1) return `${nombre}, cada uno con su tope`;
  return productos > 1 ? `${nombre} con un tope compartido` : nombre;
}

function lineasDe(tactical) {
  const porLinea = new Map();
  for (const hijo of tactical.lineas) porLinea.set(hijo.linea, [...(porLinea.get(hijo.linea) ?? []), hijo]);
  return [...porLinea.entries()].sort(([a], [b]) => a - b);
}

/** The dialog's starting values: the caps a line has and the most any of its children already used. */
export function valoresDeEdicion(tactical) {
  return {
    nombre: tactical.nombre,
    nota: tactical.nota ?? '',
    fechaHasta: tactical.fecha_hasta,
    lineas: lineasDe(tactical).map(([linea, hijos]) => ({
      linea,
      titulo: tituloDe(hijos),
      topeUnidades: vacio(hijos[0].tope_unidades) ? '' : String(hijos[0].tope_unidades),
      topeMonto: texto(hijos[0].tope_monto),
      usadas: Math.max(...hijos.map((h) => Number(h.unidades_usadas ?? 0))),
      usado: Math.max(...hijos.map((h) => Number(h.monto_usado ?? 0))),
      moneda: hijos[0].moneda,
      admiteTopes: hijos[0].modo_monto !== 'monto_total',
    })),
  };
}

/** What the form cannot send: the server judges the rest (dates against today, caps against what was used). */
export function problemaDeEdicion(valores) {
  if (!valores.nombre.trim()) return 'El nombre no puede quedar vacío.';
  if (!valores.fechaHasta) return 'Elegí la fecha hasta.';
  for (const l of valores.lineas) {
    const unidades = numeroDe(l.topeUnidades);
    if (l.topeUnidades.trim() && (unidades == null || !Number.isInteger(unidades))) {
      return `La línea ${l.linea} tiene un tope de unidades que no es un número entero.`;
    }
    if (l.topeMonto.trim() && numeroDe(l.topeMonto) == null) {
      return `La línea ${l.linea} tiene un tope de monto que no es un número.`;
    }
  }
  return null;
}

/** The PATCH body: only what changed; an emptied cap goes as null, which removes it. */
export function cuerpoDeEdicion(tactical, valores) {
  const antes = valoresDeEdicion(tactical);
  const cuerpo = {};
  const nombre = valores.nombre.trim();
  if (nombre !== antes.nombre) cuerpo.nombre = nombre;
  const nota = valores.nota.trim() || null;
  if (nota !== (tactical.nota ?? null)) cuerpo.nota = nota;
  if (valores.fechaHasta !== antes.fechaHasta) cuerpo.fecha_hasta = valores.fechaHasta;
  const lineas = [];
  for (const l of valores.lineas) {
    const previa = antes.lineas.find((a) => a.linea === l.linea);
    const cambio = { linea: l.linea };
    const unidades = numeroDe(l.topeUnidades);
    if (unidades !== numeroDe(previa.topeUnidades)) cambio.tope_unidades = unidades;
    const monto = numeroDe(l.topeMonto);
    if (monto !== numeroDe(previa.topeMonto)) cambio.tope_monto = monto;
    if (Object.keys(cambio).length > 1) lineas.push(cambio);
  }
  if (lineas.length) cuerpo.lineas = lineas;
  return cuerpo;
}
