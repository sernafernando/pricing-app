/**
 * Configuración centralizada de plugins pdfme.
 * Importar desde aquí para garantizar consistencia entre Designer y Generator.
 */
import { text, image, svg, barcodes, table, line, rectangle, ellipse } from '@pdfme/schemas';

/**
 * Plugins disponibles para Designer y Generator.
 */
export const plugins = {
  text,
  image,
  svg,
  line,
  rectangle,
  ellipse,
  ...barcodes,
  table,
};
