/**
 * Configuración centralizada de plugins pdfme.
 * Importar desde aquí para garantizar consistencia entre Designer y Generator.
 */
import { text, image, barcodes, table } from '@pdfme/schemas';

/**
 * Plugins disponibles para Designer y Generator.
 * text: texto simple y multi-variable
 * image: imágenes (logo, firma, etc.)
 * barcodes: QR, Code128, EAN13, etc.
 * table: tablas dinámicas con page breaks
 */
export const plugins = {
  text,
  image,
  ...barcodes,
  table,
};

/**
 * Lista de tipos de plugin disponibles para referencia.
 */
export const pluginTypes = [
  { type: 'text', label: 'Texto' },
  { type: 'image', label: 'Imagen' },
  { type: 'table', label: 'Tabla' },
  { type: 'qrcode', label: 'Código QR' },
  { type: 'code128', label: 'Código de barras (Code128)' },
  { type: 'ean13', label: 'Código de barras (EAN13)' },
];
