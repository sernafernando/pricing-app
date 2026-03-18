/**
 * Configuración de fuentes para pdfme (Designer + Generator).
 *
 * IMPORTANTE: pdfme solo soporta TTF estáticos (no variable fonts).
 * Los archivos con [wght] o [opsz,wght] en el nombre NO funcionan.
 *
 * Usamos fonts del repo google/fonts en su versión STATIC.
 */

const FONT_REGISTRY = {
  // --- Fuentes de sistema (open-source equivalentes estáticas) ---
  Arial: {
    data: 'https://raw.githubusercontent.com/matomo-org/travis-scripts/master/fonts/Arial.ttf',
    fallback: true,
  },
  'Arial Bold': {
    data: 'https://raw.githubusercontent.com/matomo-org/travis-scripts/master/fonts/Arial_Bold.ttf',
  },

  // --- Google Fonts (versiones STATIC, no variable) ---
  Inter: {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/inter/static/Inter_18pt-Regular.ttf',
  },
  'Inter Bold': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/inter/static/Inter_18pt-Bold.ttf',
  },
  'Open Sans': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/static/OpenSans-Regular.ttf',
  },
  'Open Sans Bold': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/static/OpenSans-Bold.ttf',
  },
  Roboto: {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/static/Roboto-Regular.ttf',
  },
  'Roboto Bold': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/static/Roboto-Bold.ttf',
  },
  'Roboto Mono': {
    data: 'https://raw.githubusercontent.com/google/fonts/main/ofl/robotomono/static/RobotoMono-Regular.ttf',
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
