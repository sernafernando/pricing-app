/**
 * Ayuda loader — the end-user help manual, one Markdown file per screen
 * under `frontend/src/ayuda/` (same pattern as `novedades/loadNovedades.js`).
 *
 * File contract:
 *   # <Screen title>
 *
 *   Área: <menu group>
 *   Ruta: <where to find it>
 *   Permiso: <what access it needs>
 *
 *   <body>
 *
 * The three header lines are optional; a file without `Área` lands under
 * "Otras pantallas". Files starting with `_` (the `_indice.md` table) and
 * `README.md` are never shown. `_indice.md` does set the ORDER: sections
 * follow the order its table lists their files (the menu order), áreas in
 * the order their first section appears; files it does not list go last,
 * by title.
 *
 * The pure logic (`parseAyuda`, `filtrarAyuda`) takes plain data so it is
 * unit-testable without Vite's `import.meta.glob`.
 */

const H1_RE = /^#\s+(.+)$/m;
const HEADER_RE = /^(Área|Area|Ruta|Permiso):\s*(.+)$/i;
const INDICE_FILE_RE = /`([^`]+\.md)`/g;
const SIN_AREA = 'Otras pantallas';

const CLAVE_HEADER = { área: 'area', area: 'area', ruta: 'ruta', permiso: 'permiso' };

function nombreDeArchivo(key) {
  // import.meta.glob keys are relative paths ("./tickets.md").
  return key.split('/').pop();
}

// The área is an h2 and the section an h3 on the page, so the body's own
// headings ("## Para qué sirve") move two levels down to stay under them.
function bajarTitulos(markdown) {
  return markdown.replace(/^(#{1,4})(\s)/gm, '##$1$2');
}

function ordenDelIndice(raw) {
  const orden = new Map();
  for (const [, archivo] of (raw || '').matchAll(INDICE_FILE_RE)) {
    if (!orden.has(archivo)) orden.set(archivo, orden.size);
  }
  return orden;
}

function parseSeccion(archivo, raw) {
  const slug = archivo.replace(/\.md$/, '');
  const h1 = raw.match(H1_RE);
  const title = h1 ? h1[1].trim() : slug;
  const resto = h1 ? raw.slice(0, h1.index) + raw.slice(h1.index + h1[0].length) : raw;

  // Header lines are only read at the very top of the body: blank lines
  // between them are fine, the first other line ends the header.
  const meta = { area: null, ruta: null, permiso: null };
  const lineas = resto.split('\n');
  let inicio = 0;
  while (inicio < lineas.length) {
    const linea = lineas[inicio].trim();
    if (linea === '') {
      inicio += 1;
      continue;
    }
    const match = linea.match(HEADER_RE);
    if (!match) break;
    meta[CLAVE_HEADER[match[1].toLowerCase()]] = match[2].trim();
    inicio += 1;
  }

  return {
    slug,
    title,
    area: meta.area || SIN_AREA,
    ruta: meta.ruta,
    permiso: meta.permiso,
    bodyMarkdown: bajarTitulos(lineas.slice(inicio).join('\n').trim()),
  };
}

/**
 * @param {Record<string, string>} rawByFilename
 * @returns {Array<{ area: string, secciones: Array<{ slug: string, title: string, area: string, ruta: string | null, permiso: string | null, bodyMarkdown: string }> }>}
 */
export function parseAyuda(rawByFilename) {
  const archivos = Object.entries(rawByFilename || {}).map(([key, raw]) => [nombreDeArchivo(key), raw]);
  const orden = ordenDelIndice(archivos.find(([archivo]) => archivo === '_indice.md')?.[1]);

  const secciones = archivos
    .filter(([archivo]) => archivo.endsWith('.md') && !archivo.startsWith('_') && archivo !== 'README.md')
    .map(([archivo, raw]) => ({ ...parseSeccion(archivo, raw), posicion: orden.get(archivo) ?? Infinity }));

  secciones.sort((a, b) => {
    if (a.posicion !== b.posicion) return a.posicion - b.posicion;
    return a.title.localeCompare(b.title, 'es');
  });

  const porArea = new Map();
  for (const { posicion: _posicion, ...seccion } of secciones) {
    if (!porArea.has(seccion.area)) porArea.set(seccion.area, []);
    porArea.get(seccion.area).push(seccion);
  }
  // "Otras pantallas" always goes last, even if one of its files is indexed.
  if (porArea.has(SIN_AREA)) {
    const sinArea = porArea.get(SIN_AREA);
    porArea.delete(SIN_AREA);
    porArea.set(SIN_AREA, sinArea);
  }

  return [...porArea.entries()].map(([area, lista]) => ({ area, secciones: lista }));
}

// Lowercase, no accents, no Markdown marks: "**Diseñar**" matches "disenar".
function normalizar(texto) {
  return (texto || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[*_`#>|[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .trim();
}

/**
 * Keeps the sections whose title, ruta, permiso or text contain `termino`
 * (case- and accent-insensitive); áreas left with no section are dropped.
 * An empty search returns `grupos` itself.
 */
export function filtrarAyuda(grupos, termino) {
  const buscado = normalizar(termino);
  if (!buscado) return grupos;
  return grupos
    .map((grupo) => ({
      ...grupo,
      secciones: grupo.secciones.filter((s) =>
        normalizar([s.title, s.ruta, s.permiso, s.bodyMarkdown].join(' ')).includes(buscado),
      ),
    }))
    .filter((grupo) => grupo.secciones.length > 0);
}

// Vite-native raw import, eager so sections are available synchronously.
const rawModules = import.meta.glob('./*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
});

export function loadAyuda() {
  return parseAyuda(rawModules);
}
