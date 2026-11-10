import { formatDateOnly } from '../../utils/dateUtils';

/**
 * Collection check of a tactical (handoffs/tactical-cobranza-tarea.md S3; API in PR #2182). Owner, 2026-11-10: "pida,
 * fecha de cuando se cobro, si es Nota de crédito (ahí número) o si es fondo en distribuidor (ahí un panel para aclarar
 * el distri) u otro y un panel para rellenar el otro. además un panel de observaciones libre, que obligatorio sea la
 * fecha no más."
 */

export const MEDIOS = [
  { value: 'nota_credito', label: 'Nota de crédito' },
  { value: 'fondo_distribuidor', label: 'Fondo en distribuidor' },
  { value: 'otro', label: 'Otro' },
];

/** The detail each medium asks: its form field and the API field it goes to. */
export const DETALLE_DE_MEDIO = {
  nota_credito: { campo: 'ncNumero', api: 'nc_numero', label: 'Número de NC', max: 100 },
  fondo_distribuidor: { campo: 'distribuidor', api: 'distribuidor', label: 'Distribuidor', max: 200 },
  otro: { campo: 'otroDetalle', api: 'otro_detalle', label: 'Detalle', max: 500 },
};

/** The form's values from a tactical's record (`null`: a tactical not collected yet). */
export const valoresDeCobranza = (cobranza) => ({
  fecha: cobranza?.fecha_cobro ?? '',
  medio: cobranza?.medio ?? '',
  ncNumero: cobranza?.nc_numero ?? '',
  distribuidor: cobranza?.distribuidor ?? '',
  otroDetalle: cobranza?.otro_detalle ?? '',
  observaciones: cobranza?.observaciones ?? '',
});

/** What stops a save, or null: only the date is required. */
export const problemaDeCobranza = (valores) => (valores.fecha ? null : 'La fecha de cobro es obligatoria.');

const texto = (valor) => valor.trim() || null;

/** The `PUT` body: only the chosen medium's detail (the API refuses another medium's), blank texts as null. */
export function cuerpoDeCobranza(valores) {
  const cuerpo = {
    fecha_cobro: valores.fecha,
    medio: valores.medio || null,
    nc_numero: null,
    distribuidor: null,
    otro_detalle: null,
    observaciones: texto(valores.observaciones),
  };
  const detalle = DETALLE_DE_MEDIO[valores.medio];
  if (detalle) cuerpo[detalle.api] = texto(valores[detalle.campo]);
  return cuerpo;
}

const DIA_MES_ANIO = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** The row's pill: Pendiente, or Cobrado with its date. */
export const estadoDeCobranza = ({ cobranza }) =>
  cobranza
    ? { texto: `Cobrado ${formatDateOnly(cobranza.fecha_cobro, DIA_MES_ANIO)}`, tono: 'success' }
    : { texto: 'Pendiente', tono: 'neutral' };
