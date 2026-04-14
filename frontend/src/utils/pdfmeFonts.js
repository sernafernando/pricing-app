/**
 * Configuración de fuentes para pdfme (Designer + Generator).
 *
 * IMPORTANTE: pdfme solo soporta TTF estáticos como ArrayBuffer.
 * Las fuentes se sirven desde /public/fonts/ y se fetchean como ArrayBuffer.
 * Se cachean en memoria después de la primera carga.
 */

const FONT_FILES = {
  Arial: { path: '/fonts/Arial-Regular.ttf', fallback: true },
  'Arial Bold': { path: '/fonts/Arial-Bold.ttf' },
  Inter: { path: '/fonts/Inter-Regular.ttf' },
  'Inter Bold': { path: '/fonts/Inter-Bold.ttf' },
  'Inter Italic': { path: '/fonts/Inter-Italic.ttf' },
  'Inter Bold Italic': { path: '/fonts/Inter-BoldItalic.ttf' },
  'Open Sans': { path: '/fonts/OpenSans-Regular.ttf' },
  'Open Sans Bold': { path: '/fonts/OpenSans-Bold.ttf' },
  'Open Sans Italic': { path: '/fonts/OpenSans-Italic.ttf' },
  'Open Sans Bold Italic': { path: '/fonts/OpenSans-BoldItalic.ttf' },
  Roboto: { path: '/fonts/Roboto-Regular.ttf' },
  'Roboto Bold': { path: '/fonts/Roboto-Bold.ttf' },
  'Roboto Italic': { path: '/fonts/Roboto-Italic.ttf' },
  'Roboto Bold Italic': { path: '/fonts/Roboto-BoldItalic.ttf' },
  'Roboto Mono': { path: '/fonts/RobotoMono-Regular.ttf' },
  'Roboto Mono Italic': { path: '/fonts/RobotoMono-Italic.ttf' },
};

let fontCache = null;

/**
 * Carga todas las fuentes como ArrayBuffer (fetch + cache en memoria).
 * @returns {Promise<Record<string, { data: ArrayBuffer, fallback?: boolean }>>}
 */
export const getFont = async () => {
  if (fontCache) return fontCache;

  const entries = Object.entries(FONT_FILES);
  const results = await Promise.all(
    entries.map(async ([name, config]) => {
      const res = await fetch(config.path);
      const data = await res.arrayBuffer();
      const entry = { data };
      if (config.fallback) entry.fallback = true;
      return [name, entry];
    })
  );

  fontCache = Object.fromEntries(results);
  return fontCache;
};

/**
 * Lista de nombres de fuente disponibles (para UI/selects).
 */
export const fontNames = Object.keys(FONT_FILES);
