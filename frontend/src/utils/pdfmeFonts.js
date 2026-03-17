/**
 * Configuración de fuentes para pdfme (Designer + Generator).
 *
 * pdfme necesita los archivos TTF como ArrayBuffer o URL string.
 * Usamos URLs a Google Fonts CDN (estáticas, confiables, gratis).
 *
 * Para agregar una fuente:
 * 1. Buscar la URL TTF en https://fonts.google.com
 * 2. Agregar una entrada al objeto FONT_REGISTRY
 * 3. La primera con `fallback: true` es la fuente por defecto
 *
 * Orden de prioridad definido por el usuario:
 * - Sistema: Arial, Times New Roman
 * - Google Fonts: Inter, Open Sans, Roboto
 */

// Google Fonts sirve TTF estáticos desde este patrón:
// https://raw.githubusercontent.com/google/fonts/main/ofl/{font}/{font}-Regular.ttf
// Para fuentes de sistema (Arial, Times) usamos una alternativa open-source equivalente.

const FONT_REGISTRY = {
  // --- Fuentes de sistema (open-source equivalentes) ---
  Arial: {
    data: 'https://raw.githubusercontent.com/matomo-org/travis-scripts/master/fonts/Arial.ttf',
    fallback: true,
  },
  'Arial Bold': {
    data: 'https://raw.githubusercontent.com/matomo-org/travis-scripts/master/fonts/Arial_Bold.ttf',
  },
  'Times New Roman': {
    data: 'https://raw.githubusercontent.com/AreebaArowormo5/FontsFree/master/Times-New-Roman/times%20new%20roman.ttf',
  },
  'Times New Roman Bold': {
    data: 'https://raw.githubusercontent.com/AreebaArowormo5/FontsFree/master/Times-New-Roman/times%20new%20roman%20bold.ttf',
  },

  // --- Google Fonts ---
  Inter: {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf',
  },
  'Open Sans': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth%2Cwght%5D.ttf',
  },
  Roboto: {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf',
  },
  'Roboto Mono': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/robotomono/RobotoMono%5Bwght%5D.ttf',
  },
};

/**
 * Retorna el objeto font listo para pasarle a pdfme.
 * pdfme acepta URLs directamente — las descarga bajo demanda.
 */
export const getFont = () => FONT_REGISTRY;

/**
 * Lista de nombres de fuente disponibles (para UI/selects).
 */
export const fontNames = Object.keys(FONT_REGISTRY);
