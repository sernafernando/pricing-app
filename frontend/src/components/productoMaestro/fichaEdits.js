/**
 * The product master ficha's edits: what each field shows while being edited, and the requests that save only what
 * changed (`PATCH /productos-propios/{id}/maestro`, `PUT /producto-specs/{id}`).
 *
 * `edits = { general: { campo: string }, textos: { clave: { fuente, texto? } }, specs: { campo: string },
 * noAplica: { campo: bool } }`. An edit equal to what the server holds is not a change.
 */

export const EDITS_VACIOS = { general: {}, textos: {}, specs: {}, noAplica: {} };

/** The general fields in the mock's order, with their section, unit and kind of input. */
export const GENERAL = [
  { key: 'nombre', etiqueta: 'Nombre', seccion: 'Identidad', ancho: true },
  { key: 'ean', etiqueta: 'EAN', seccion: 'Identidad' },
  { key: 'codigo_fabricante', etiqueta: 'Código del fabricante', seccion: 'Identidad' },
  { key: 'marca_id', etiqueta: 'Marca', seccion: 'Identidad', tipo: 'marca' },
  { key: 'categoria_id', etiqueta: 'Categoría', seccion: 'Identidad', tipo: 'categoria' },
  { key: 'subcategoria_id', etiqueta: 'Subcategoría', seccion: 'Identidad', tipo: 'subcategoria' },
  { key: 'garantia_dias', etiqueta: 'Garantía', unidad: 'días', seccion: 'Logística y garantía', tipo: 'entero' },
  { key: 'peso_g', etiqueta: 'Peso', unidad: 'g', seccion: 'Logística y garantía', tipo: 'decimal' },
  { key: 'ancho_cm', etiqueta: 'Ancho', unidad: 'cm', seccion: 'Logística y garantía', tipo: 'decimal' },
  { key: 'largo_cm', etiqueta: 'Largo', unidad: 'cm', seccion: 'Logística y garantía', tipo: 'decimal' },
  { key: 'alto_cm', etiqueta: 'Alto', unidad: 'cm', seccion: 'Logística y garantía', tipo: 'decimal' },
  { key: 'unidades_caja', etiqueta: 'Unidades por caja', unidad: 'u.', seccion: 'Logística y garantía', tipo: 'entero', gestionFull: true },
];

const SELECTS = new Set(['marca', 'categoria', 'subcategoria']);
const ENTEROS = new Set(['entero', ...SELECTS]);

export const TEXTOS = [
  { clave: 'titulo_ml', etiqueta: 'Título ML', largo: false },
  { clave: 'titulo_web', etiqueta: 'Título web', largo: false },
  { clave: 'descripcion_ml', etiqueta: 'Descripción ML', largo: true },
  { clave: 'descripcion_web', etiqueta: 'Descripción web', largo: true },
];

const texto = (value) => (value === null || value === undefined ? '' : String(value));

/** What the server holds for a general field, as the input shows it. */
export function original(maestro, def) {
  if (def.gestionFull) return texto(maestro.unidades_caja);
  return texto(maestro.campos[def.key]?.valor);
}

/** The general field's value on screen: the edit, else the stored one. */
export function valorGeneral(maestro, edits, def) {
  return def.key in edits.general ? edits.general[def.key] : original(maestro, def);
}

function convertir(def, value) {
  const limpio = value.trim();
  if (limpio === '') return null;
  if (ENTEROS.has(def.tipo)) return Number(limpio);
  if (def.tipo === 'decimal') return limpio.replace(',', '.');
  return limpio;
}

/** A text as shown: the edited source and own text, else the server's. */
export function textoActual(maestro, edits, clave) {
  const server = maestro.textos[clave] ?? { fuente: null, valor: null, fuentes: {} };
  const edit = edits.textos[clave];
  const fuente = (edit ? edit.fuente : server.fuente) ?? 'propio';
  if (!edit) return { fuente, valor: texto(server.valor) };
  return { fuente, valor: fuente === 'propio' ? texto(edit.texto) : texto(server.fuentes[fuente]) };
}

function textoCambio(maestro, edits, clave) {
  const edit = edits.textos[clave];
  if (!edit) return null;
  const server = maestro.textos[clave];
  if (edit.fuente === 'propio') {
    if (server?.fuente === 'propio' && texto(server.valor) === texto(edit.texto)) return null;
    return { fuente: 'propio', texto: edit.texto ?? '' };
  }
  return server?.fuente === edit.fuente ? null : { fuente: edit.fuente };
}

/** The maestro PATCH body with only what changed; null when nothing did. */
export function patchMaestro(maestro, edits) {
  const body = {};
  GENERAL.forEach((def) => {
    if (!(def.key in edits.general)) return;
    if (edits.general[def.key].trim() === original(maestro, def)) return;
    body[def.key] = convertir(def, edits.general[def.key]);
  });
  const textos = {};
  TEXTOS.forEach(({ clave }) => {
    const cambio = textoCambio(maestro, edits, clave);
    if (cambio) textos[clave] = cambio;
  });
  if (Object.keys(textos).length) body.textos = textos;
  return Object.keys(body).length ? body : null;
}

/** A spec field as shown: its value, whether it is marked "No aplica" and whether either was edited. */
export function specActual(campo, edits) {
  const na = campo.campo in edits.noAplica ? edits.noAplica[campo.campo] : campo.origen === 'no_aplica';
  const editado = campo.campo in edits.specs;
  const valor = editado ? edits.specs[campo.campo] : texto(campo.valor);
  return { na, valor: na ? '' : valor, editado, naEditado: campo.campo in edits.noAplica };
}

/** The specs PUT body with only what changed; null when nothing did. */
export function bodySpecs(campos, edits) {
  const valores = {};
  const noAplica = {};
  campos.forEach((c) => {
    const naServer = c.origen === 'no_aplica';
    if (c.campo in edits.noAplica && edits.noAplica[c.campo] !== naServer) noAplica[c.campo] = edits.noAplica[c.campo];
    const na = c.campo in edits.noAplica ? edits.noAplica[c.campo] : naServer;
    if (!na && c.campo in edits.specs && edits.specs[c.campo].trim() !== texto(c.valor)) {
      valores[c.campo] = edits.specs[c.campo].trim() || null;
    }
  });
  if (!Object.keys(valores).length && !Object.keys(noAplica).length) return null;
  return { valores, no_aplica: noAplica };
}

/** How many changes "Guardar" sends. */
export function contarCambios(maestro, specs, edits) {
  const patch = maestro ? patchMaestro(maestro, edits) : null;
  const generales = patch ? Object.keys(patch).filter((k) => k !== 'textos').length : 0;
  const textos = patch?.textos ? Object.keys(patch.textos).length : 0;
  const body = specs ? bodySpecs(specs.campos, edits) : null;
  const specsN = body ? new Set([...Object.keys(body.valores), ...Object.keys(body.no_aplica)]).size : 0;
  return generales + textos + specsN;
}

/** Fields complete (with a value or "No aplica") out of the total, on screen. */
export function completos(campos, edits) {
  return campos.filter((c) => {
    const actual = specActual(c, edits);
    return actual.na || actual.valor.trim() !== '';
  }).length;
}
