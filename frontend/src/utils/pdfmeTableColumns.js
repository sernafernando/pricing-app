/**
 * Helpers PUROS para variar la forma de las tablas de un template pdfme en
 * tiempo de generación.
 *
 * Por qué existen: hay UN template por documento en la base, pero algunas
 * columnas son opcionales según lo que pida el usuario al imprimir. Duplicar
 * el template por cada combinación sería otra copia que se desincroniza; en
 * cambio, la columna se saca del template en memoria justo antes de generar.
 *
 * Ninguna función de este módulo muta su argumento: siempre devuelven un
 * template nuevo (o el mismo, sin tocar, cuando no hay nada que hacer).
 */

/**
 * Reescala anchos de columna para que sumen EXACTAMENTE 100.
 *
 * El último elemento absorbe el residuo (`100 - suma de los anteriores`) en
 * vez de calcularse por regla de tres, así que la suma izquierda-a-derecha del
 * resultado da 100 exacto en punto flotante: el error de redondeo de la resta
 * queda muy por debajo del medio-ulp de 100.
 *
 * @param {number[]} widths
 * @returns {number[]}
 */
const rescaleToHundred = (widths) => {
  if (widths.length === 0) return [];

  const total = widths.reduce((acc, w) => acc + w, 0);
  // Anchos degenerados (todos 0, o negativos): repartir en partes iguales en
  // vez de dividir por cero y escupir NaN al PDF.
  const scaled =
    total > 0 ? widths.map((w) => (w * 100) / total) : widths.map(() => 100 / widths.length);

  const head = scaled.slice(0, -1);
  const partial = head.reduce((acc, w) => acc + w, 0);
  return [...head, 100 - partial];
};

/**
 * Devuelve una COPIA del template sin la última columna de cada campo `table`,
 * con los anchos restantes reescalados para seguir sumando 100.
 *
 * Las tablas con una sola columna (o sin `head`) se dejan intactas: sacarles la
 * última columna las dejaría sin ninguna.
 *
 * @param {object} template - template_json de pdfme
 * @returns {object} template nuevo
 */
export const dropLastTableColumn = (template) => {
  if (!template) return template;

  const clone = structuredClone(template);
  for (const page of clone.schemas || []) {
    for (const field of page) {
      if (field.type !== 'table') continue;
      if (!Array.isArray(field.head) || field.head.length <= 1) continue;

      field.head = field.head.slice(0, -1);
      if (Array.isArray(field.headWidthPercentages)) {
        field.headWidthPercentages = rescaleToHundred(field.headWidthPercentages.slice(0, -1));
      }
    }
  }
  return clone;
};

/**
 * Aplica (o no) la última columna opcional de las tablas del template.
 *
 * @param {object} template - template_json de pdfme
 * @param {boolean} incluir - true deja el template como está; false saca la columna
 * @returns {object}
 */
export const withOptionalLastColumn = (template, incluir) =>
  incluir ? template : dropLastTableColumn(template);
