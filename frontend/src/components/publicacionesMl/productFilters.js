import { decodeKey, encodeKey, NO_GROUP } from './groupNodes';

/**
 * The product filters of Publicaciones ML (marca / categoría / subcategoría / PM) between the URL and the shared
 * `ProductFiltersPanel`. The URL keeps what `/view/items`, `/view/products` and `/view/groups` take: brands and
 * categories as the backend keys them (`encode_key`: a comma inside a name escaped, so the csv param keeps it as ONE
 * value), subcategories and PMs as id strings. The panel works with the plain names and numeric ids.
 */
export const PRODUCT_FILTER_KEYS = ['marcas', 'categorias', 'subcategorias', 'pms'];

export const EMPTY_PRODUCT_FILTERS = { marcas: [], categorias: [], subcategorias: [], pms: [] };

// A non-numeric token (the backend's "none" bucket) stays as it came.
const toId = (token) => (/^\d+$/.test(token) ? Number(token) : token);

/** URL filters -> the panel's value. */
export function toPanelValue(filters) {
  return {
    marcas: filters.marcas.map(decodeKey),
    categorias: filters.categorias.map(decodeKey),
    subcategorias: filters.subcategorias.map(toId),
    pms: filters.pms.map(toId),
  };
}

/** The panel's value -> URL filters (the inverse of `toPanelValue`). */
export function fromPanelValue(value) {
  return {
    marcas: value.marcas.map(encodeKey),
    categorias: value.categorias.map(encodeKey),
    subcategorias: value.subcategorias.map(String),
    pms: value.pms.map(String),
  };
}

const LABELS = { marcas: 'Marca', categorias: 'Categoría', subcategorias: 'Subcategoría', pms: 'PM' };

// The "none" bucket (`NO_GROUP`) by the name the grouped view gives it (the backend's `NO_LABELS`).
const NONE_LABELS = { marcas: 'Sin marca', categorias: 'Sin categoría', subcategorias: 'Sin subcategoría' };

function namesOf(options = {}) {
  const subcategorias = new Map(
    (options.subcategorias ?? []).flatMap((group) => (group.subcategorias ?? []).map((sub) => [String(sub.id), sub.nombre])),
  );
  const pms = new Map((options.pms ?? []).map((pm) => [String(pm.id), pm.nombre]));
  return { subcategorias, pms };
}

function nameOf(key, token, names) {
  if (token === NO_GROUP && key in NONE_LABELS) return NONE_LABELS[key];
  return key in names ? names[key].get(token) : decodeKey(token);
}

/**
 * One chip per active value: its label (a subcategory or PM by name when the options have it, by id otherwise) and
 * the `setFilters` update that removes it.
 */
export function activeProductChips(filters, options) {
  const names = namesOf(options);
  return PRODUCT_FILTER_KEYS.flatMap((key) =>
    // A value repeated in the URL is one chip: unique ids, and removing it drops every copy of that value.
    [...new Set(filters[key])].map((token) => {
      const name = nameOf(key, token, names);
      return {
        id: `${key}:${token}`,
        label: name ? `${LABELS[key]}: ${name}` : `${LABELS[key]} #${token}`,
        remove: { [key]: filters[key].filter((other) => other !== token) },
      };
    }),
  );
}
