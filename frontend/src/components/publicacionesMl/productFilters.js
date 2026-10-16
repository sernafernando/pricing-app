import { decodeKey, encodeKey } from './groupNodes';

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

function namesOf(options = {}) {
  const subcategorias = new Map(
    (options.subcategorias ?? []).flatMap((group) => (group.subcategorias ?? []).map((sub) => [String(sub.id), sub.nombre])),
  );
  const pms = new Map((options.pms ?? []).map((pm) => [String(pm.id), pm.nombre]));
  return { subcategorias, pms };
}

/**
 * One chip per active value: its label (a subcategory or PM by name when the options have it, by id otherwise) and
 * the `setFilters` update that removes it.
 */
export function activeProductChips(filters, options) {
  const names = namesOf(options);
  return PRODUCT_FILTER_KEYS.flatMap((key) =>
    filters[key].map((token) => {
      const name = key in names ? names[key].get(token) : decodeKey(token);
      return {
        id: `${key}:${token}`,
        label: name ? `${LABELS[key]}: ${name}` : `${LABELS[key]} #${token}`,
        remove: { [key]: filters[key].filter((other) => other !== token) },
      };
    }),
  );
}
