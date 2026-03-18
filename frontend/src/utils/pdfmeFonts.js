/**
 * Configuración de fuentes para pdfme (Designer + Generator).
 *
 * IMPORTANTE: pdfme solo soporta TTF estáticos (no variable fonts).
 * Las fuentes se sirven desde /public/fonts/ (Vite las sirve como estáticas).
 * pdfme acepta URLs — las descarga y convierte a ArrayBuffer internamente.
 */

const FONT_REGISTRY = {
  Arial: {
    data: '/fonts/Arial-Regular.ttf',
    fallback: true,
  },
  'Arial Bold': {
    data: '/fonts/Arial-Bold.ttf',
  },
  Inter: {
    data: '/fonts/Inter-Regular.ttf',
  },
  'Inter Bold': {
    data: '/fonts/Inter-Bold.ttf',
  },
  'Open Sans': {
    data: '/fonts/OpenSans-Regular.ttf',
  },
  'Open Sans Bold': {
    data: '/fonts/OpenSans-Bold.ttf',
  },
  Roboto: {
    data: '/fonts/Roboto-Regular.ttf',
  },
  'Roboto Bold': {
    data: '/fonts/Roboto-Bold.ttf',
  },
  'Roboto Mono': {
    data: '/fonts/RobotoMono-Regular.ttf',
  },
};

/**
 * Retorna el objeto font listo para pasarle a pdfme.
 */
export const getFont = () => FONT_REGISTRY;

/**
 * Lista de nombres de fuente disponibles (para UI/selects).
 */
export const fontNames = Object.keys(FONT_REGISTRY);
