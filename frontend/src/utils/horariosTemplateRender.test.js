/**
 * Render REAL del template de registro de horarios.
 *
 * POR QUÉ ESTE TEST EXISTE
 * ------------------------
 * El documento salió roto en producción —las tablas de días montadas sobre el
 * encabezado— con 897 tests en verde. Los tests que había verificaban la
 * geometría DECLARADA del template ("las dos tablas están lado a lado"), que
 * era cierta y no servía para nada: pdfme mueve las tablas DESPUÉS, en
 * `dynamicTemplate.processDynamicPage`, que recorre las tablas de la página
 * acumulando un `totalYOffset` y ubica cada una en `baseY + totalYOffset`.
 * Con dos tablas arrancando en el mismo `y`, la segunda hereda el
 * desplazamiento de la primera y sube.
 *
 * Así que acá no se asserta sobre el template: se genera un PDF de verdad con
 * @pdfme/generator y se assertan propiedades de la SALIDA.
 *
 * QUÉ SE MIDE Y CÓMO
 * ------------------
 * - Cantidad de páginas: se cuenta sobre el PDF real. pdf-lib guarda los
 *   objetos en object streams comprimidos con Flate, así que hay que
 *   inflarlos antes de contar `/Type /Page`.
 * - Posición del contenido: se leen las matrices `1 0 0 1 X Y Tm` del content
 *   stream, que son las coordenadas exactas en puntos donde el PDF dibuja cada
 *   corrida de texto.
 *
 * Lo que NO se puede leer del PDF es el TEXTO: las fuentes se embeben como
 * subset TTF y los operadores `Tj` llevan glyph IDs en hexa, no caracteres.
 * Por eso "la primera celda HH:MM" se identifica por su X —los bordes
 * izquierdos de columna, calculados desde el propio template— y no por su
 * valor. La clasificación se autovalida: si un campo del encabezado cayera por
 * casualidad en una X de columna, la cuenta de celdas dejaría de dar
 * `columnas × (encabezado + filas)` y el test falla en vez de mentir.
 *
 * FUENTES: `getFont()` de `pdfmeFonts.js` hace `fetch('/fonts/*.ttf')` y en
 * Node no hay servidor que lo atienda. Se leen los TTF con `fs`.
 */
import { Buffer } from 'node:buffer';
import { readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { describe, it, expect, beforeAll } from 'vitest';
import { generate } from '@pdfme/generator';
import { mm2pt, pt2mm } from '@pdfme/common';
import { text, image, line, rectangle, ellipse, table } from '@pdfme/schemas';

/**
 * `import.meta.dirname` y NO `new URL(rel, import.meta.url)`: Vite reescribe
 * ese patrón como import de asset y acá devuelve `undefined`, así que el
 * `readFileSync` termina buscando un archivo llamado literalmente "undefined".
 */
const fromRoot = (rel) => `${import.meta.dirname}/../../${rel}`;

const leerTemplate = () =>
  JSON.parse(readFileSync(fromRoot('src/test/fixtures/horarios-template.json'), 'utf8'));

/**
 * `new Uint8Array(...)` sobre el Buffer de `readFileSync` no es decorativo: el
 * Buffer viene del realm de Node y la validación de pdfme corre contra el
 * `Uint8Array` del realm de jsdom, así que el `instanceof` falla y rechaza la
 * fuente con "ERROR POSITION: options.font.Arial.data".
 */
const leerFuente = (archivo) => new Uint8Array(readFileSync(fromRoot(`public/fonts/${archivo}`)));

// Arial alcanza: es la única familia que usa este template (regular + bold).
// `fallback: true` es obligatorio, pdfme exige exactamente una fuente fallback.
const FUENTES = {
  Arial: { data: leerFuente('Arial-Regular.ttf'), fallback: true },
  'Arial Bold': { data: leerFuente('Arial-Bold.ttf') },
};

const PLUGINS = { text, image, line, rectangle, ellipse, table };

// =============================================================================
// DATOS DE ENTRADA
// =============================================================================

/** Filas con las 4 celdas llenas: una celda vacía no dibuja texto y no contaría. */
const filas = (n) =>
  Array.from({ length: n }, (_, i) => [
    `Lun ${String((i % 28) + 1).padStart(2, '0')}/08`,
    '08:57',
    '18:03',
    '09:06',
  ]);

const inputPara = (n) => ({
  nombre_completo: 'Pérez, Juan',
  legajo: '0042',
  dni: '30111222',
  cuil: '20301112223',
  area: 'Depósito',
  puesto: 'Operario',
  periodo: '01/08/2026 - 31/08/2026',
  total_horas: '176:30',
  total_dias: String(n),
  fecha_emision: '05/09/2026',
  tabla_dias: JSON.stringify(filas(n)),
});

const render = (template, input) =>
  generate({ template, inputs: [input], plugins: PLUGINS, options: { font: FUENTES } });

// =============================================================================
// LECTURA DEL PDF GENERADO
// =============================================================================

/**
 * Infla todos los streams Flate del PDF y devuelve su contenido como texto
 * latin1. Los que no son Flate (o no descomprimen) se descartan.
 */
const inflarStreams = (bytes) => {
  const buf = Buffer.from(bytes);
  const salida = [];
  let cursor = 0;
  for (;;) {
    const inicioKw = buf.indexOf('stream', cursor);
    if (inicioKw === -1) break;
    let inicio = inicioKw + 'stream'.length;
    if (buf[inicio] === 0x0d) inicio += 1; // CR opcional antes del LF
    if (buf[inicio] === 0x0a) inicio += 1;
    const fin = buf.indexOf('endstream', inicio);
    if (fin === -1) break;
    try {
      salida.push(inflateSync(buf.subarray(inicio, fin)).toString('latin1'));
    } catch {
      // Stream no comprimido con Flate: no aporta nada a lo que medimos.
    }
    cursor = fin + 'endstream'.length;
  }
  return salida;
};

/** Cantidad de páginas del PDF real. `[^s]` para no contar `/Type /Pages`. */
const contarPaginas = (bytes) =>
  (inflarStreams(bytes).join('\n').match(/\/Type\s*\/Page[^s]/g) || []).length;

/**
 * Todas las corridas de texto dibujadas, en milímetros DESDE ARRIBA — el mismo
 * sistema de coordenadas que usa el template, así que los números son
 * comparables contra `position.y` a ojo.
 */
const textosDibujados = (bytes, altoPaginaMm) => {
  const contenido = inflarStreams(bytes)
    .filter((s) => s.includes(' Tf'))
    .join('\n');
  const altoPt = mm2pt(altoPaginaMm);

  return [...contenido.matchAll(/1 0 0 1 ([-\d.]+) ([-\d.]+) Tm/g)].map((m) => ({
    x: pt2mm(Number(m[1])),
    y: pt2mm(altoPt - Number(m[2])),
  }));
};

// =============================================================================
// GEOMETRÍA DERIVADA DEL TEMPLATE
// =============================================================================

const campoTabla = (template) => template.schemas[0].find((f) => f.type === 'table');

/**
 * Borde izquierdo de texto de cada columna: `x` de la tabla + los anchos
 * acumulados + el padding izquierdo. Con las celdas alineadas a la izquierda,
 * es exactamente la X donde pdfme dibuja cada celda.
 */
const bordesDeColumna = (tabla) => {
  const padding = tabla.bodyStyles.padding.left;
  let acumulado = tabla.position.x;
  return tabla.headWidthPercentages.map((pct) => {
    const borde = acumulado + padding;
    acumulado += (pct / 100) * tabla.width;
    return borde;
  });
};

/**
 * El cuerpo de la tabla se dibuja 0.1mm a la derecha del encabezado (el ancho
 * del borde de celda), así que la tolerancia tiene que cubrir ambos. 0.2mm
 * sigue siendo mucho más chico que cualquier separación real entre campos.
 */
const TOLERANCIA_MM = 0.2;

const esCelda = (bordes) => (dibujo) =>
  bordes.some((borde) => Math.abs(dibujo.x - borde) < TOLERANCIA_MM);

/**
 * Los campos del encabezado: los que el builder emite ANTES de la tabla.
 *
 * Se toman por ORDEN EN EL ARRAY y no por `y`, a propósito. Definirlos como
 * "los que están arriba de la tabla" haría el test circular: bajando la tabla
 * sobre el encabezado, la banda del encabezado se encogería sola y el test
 * seguiría en verde. El orden del array es el orden visual con el que
 * `template_horarios()` los apila y no se mueve cuando cambia la geometría.
 */
const camposDelEncabezado = (template) => {
  const pagina = template.schemas[0];
  return pagina.slice(0, pagina.findIndex((f) => f.type === 'table'));
};

/** Dónde termina el encabezado. Es la banda que el bug invadía. */
const pieDelEncabezado = (template) =>
  Math.max(...camposDelEncabezado(template).map((f) => f.position.y + f.height));

/**
 * Guarda de regresión: nombres de los campos `table` que comparten `position.y`
 * con otro campo `table` de la misma página. Esa es LA forma que rompe.
 */
const tablasQueCompartenY = (template) => {
  const repetidos = [];
  for (const pagina of template.schemas || []) {
    const porY = new Map();
    for (const campo of pagina) {
      if (campo.type !== 'table') continue;
      const misma = porY.get(campo.position.y) || [];
      misma.push(campo.name);
      porY.set(campo.position.y, misma);
    }
    for (const nombres of porY.values()) {
      if (nombres.length > 1) repetidos.push(...nombres);
    }
  }
  return repetidos;
};

/** Reconstruye el template de dos tablas lado a lado que estaba en producción. */
const conDosTablasEnElMismoY = (template) => {
  const pagina = template.schemas[0];
  const primera = campoTabla(template);
  primera.width = 85;

  const segunda = structuredClone(primera);
  segunda.name = 'tabla_dias_2';
  segunda.position = { x: primera.position.x + 95, y: primera.position.y };
  pagina.push(segunda);

  return template;
};

// =============================================================================
// TESTS
// =============================================================================

describe('registro de horarios — PDF generado de verdad', () => {
  let template;
  let altoPagina;

  beforeAll(() => {
    template = leerTemplate();
    altoPagina = template.basePdf.height;
  });

  it('un mes entero (31 días) entra en UNA sola página', async () => {
    // 31 es el requerimiento (un mes completo), no el límite: con esta
    // geometría el último rango de una página medido es de 37 días. Esos 6
    // días de aire son lo que aguanta un retoque del encabezado o del pie.
    const pdf = await render(template, inputPara(31));

    expect(contarPaginas(pdf)).toBe(1);
  });

  it('el encabezado del template son los campos previos a la tabla', () => {
    // Premisa del test de abajo, explícita: si alguien reordena el builder y
    // el encabezado deja de ser el prefijo del array, esto avisa acá y no
    // deja el test de solapamiento midiendo cualquier cosa.
    const nombres = camposDelEncabezado(template).map((f) => f.name);

    expect(nombres[0]).toBe('__logo__');
    expect(nombres.at(-1)).toBe('puesto');
    expect(nombres).toContain('__linea_header__');
    expect(nombres).not.toContain('total_horas');
  });

  it('ninguna celda de la tabla cae dentro de la banda del encabezado', async () => {
    const pdf = await render(template, inputPara(31));
    const dibujos = textosDibujados(pdf, altoPagina);
    const bordes = bordesDeColumna(campoTabla(template));
    const celdas = dibujos.filter(esCelda(bordes));

    // Autovalidación de la clasificación: 4 columnas × (1 encabezado + 31
    // filas). Si un campo del header cayera en una X de columna, esto falla.
    expect(celdas).toHaveLength(bordes.length * (31 + 1));

    const primeraCelda = Math.min(...celdas.map((c) => c.y));
    expect(primeraCelda).toBeGreaterThan(pieDelEncabezado(template));
  });

  it('el encabezado se dibuja siempre en el mismo lugar, crezca lo que crezca la tabla', async () => {
    const bordes = bordesDeColumna(campoTabla(template));
    const header = async (dias) => {
      const pdf = await render(template, inputPara(dias));
      return textosDibujados(pdf, altoPagina)
        .filter((d) => !esCelda(bordes)(d))
        .filter((d) => d.y < pieDelEncabezado(template))
        .map((d) => `${d.x.toFixed(3)}:${d.y.toFixed(3)}`)
        .sort();
    };

    // El bug era exactamente esto: la tabla crecía o encogía y algo se movía
    // dentro de la banda del encabezado.
    expect(await header(31)).toEqual(await header(5));
  });

  it('un rango largo (45 días) pagina a más de una página sin explotar', async () => {
    // La versión de dos tablas moría acá con
    // `TypeError: Cannot read properties of undefined (reading 'push')`
    // en `placeRowsOnPages`, así que que NO tire ya es información.
    const pdf = await render(template, inputPara(45));

    expect(contarPaginas(pdf)).toBeGreaterThan(1);
  });
});

describe('guarda: dos tablas no pueden compartir `y`', () => {
  it('el template de horarios no tiene tablas compartiendo `y`', () => {
    expect(tablasQueCompartenY(leerTemplate())).toEqual([]);
  });

  it('detecta la forma exacta que rompía en producción', () => {
    const roto = conDosTablasEnElMismoY(leerTemplate());

    expect(tablasQueCompartenY(roto)).toEqual(['tabla_dias', 'tabla_dias_2']);
  });

  it('esa forma hace explotar a pdfme, no es una preferencia de estilo', async () => {
    const roto = conDosTablasEnElMismoY(leerTemplate());
    const input = {
      ...inputPara(31),
      tabla_dias: JSON.stringify(filas(16)),
      tabla_dias_2: JSON.stringify(filas(15)),
    };

    await expect(render(roto, input)).rejects.toThrow(/Cannot read properties of undefined/);
  });
});
